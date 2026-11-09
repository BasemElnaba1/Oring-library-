import frappe
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, now_datetime

class LibraryTransaction(Document):
    def validate(self):
        """يتم تنفيذ هذه الدالة تلقائياً قبل حفظ المستند"""
        if flt(self.late_fee) < 0:
            frappe.throw("لا يمكن أن تكون رسوم التأخير سالبة.")
        if self.type == "Issue" and self.request_status == "Rejected":
            if self.docstatus == 1:
                frappe.throw("لا يمكن اعتماد طلب مرفوض.")
            return
        if self.type == "Issue":
            self.request_status = self.request_status or "Pending"
            self.validate_member()
            self.validate_article()
        elif self.type == "Return":
            self.validate_return()
        
        self.calculate_rental_details()

    def before_submit(self):
        # Recheck eligibility under locks: another request may have been
        # approved since this draft was created.
        frappe.get_doc("Library Member", self.library_member, for_update=True)
        frappe.get_doc("Article", self.article, for_update=True)
        self.validate()
        self.submitted_on = now_datetime()
        if self.type == "Issue":
            self.request_status = "Approved"

    def validate_return(self):
        article = frappe.get_doc("Article", self.article)
        if article.status != "Issued":
            frappe.throw("لا يمكن إرجاع كتاب غير مستعار حالياً.")
        issues = frappe.get_all(
            "Library Transaction",
            filters={"article": self.article, "type": "Issue", "docstatus": 1},
            fields=["name", "library_member"],
            order_by="submitted_on desc, creation desc",
            limit_page_length=1,
        )
        if not issues or issues[0].library_member != self.library_member:
            frappe.throw("يجب إرجاع الكتاب بواسطة العضو الذي استعاره.")
        if self.reference_issue and self.reference_issue != issues[0].name:
            frappe.throw("معاملة الاستعارة لا تطابق الكتاب المستعار حالياً.")
        self.reference_issue = issues[0].name

    def validate_member(self):
        """التحقق من حالة العضو وحدوده المسموحة"""
        member = frappe.get_doc("Library Member", self.library_member)
        
        # 1. فحص ما إذا كان العضو محظوراً
        if member.is_suspended:
            frappe.throw(f"العضو {member.first_name} محظور حالياً من التأجير بسبب مديونيات أو مخالفات!")

        # 2. حساب عدد الكتب المستعارة حالياً لدى العضو
        active_rentals = frappe.db.count("Library Transaction", {
            "library_member": self.library_member,
            "type": "Issue",
            "docstatus": 1  # المعاملات المؤكدة فقط
        }) - frappe.db.count("Library Transaction", {
            "library_member": self.library_member,
            "type": "Return",
            "docstatus": 1
        })

        max_allowed = member.max_active_rentals or 3
        if active_rentals >= max_allowed:
            frappe.throw(f"تجاوز العضو الحد الأقصى المسموح به لاستعارة الكتب! الحد الحالي: {max_allowed} كتب.")

    def validate_article(self):
        """التحقق من جاهزية الكتاب للتأجير"""
        article = frappe.get_doc("Article", self.article)
        
        # 1. التأكد من أن الكتاب متاح للتأجير
        if hasattr(article, "is_rentable") and not article.is_rentable:
            frappe.throw(f"الكتاب '{article.title}' للعرض فقط وغير متاح للتأجير.")

        # 2. التأكد من أن الكتاب غير مستعار حالياً
        if article.status == "Issued":
            frappe.throw(f"الكتاب '{article.title}' مستعار حالياً وغير متاح في الوقت الحالي!")

    def calculate_rental_details(self):
        """حساب التواريخ المخططة والتكلفة المالية"""
        if self.type == "Issue":
            # جلب سعر الإيجار اليومي من بيانات الكتاب
            rental_rate = frappe.db.get_value("Article", self.article, "rental_rate_per_day") or 0
            
            # تحديد عدد الأيام (افتراضياً 7 أيام إذا لم يحدد المستخدم)
            days = 7 if self.rental_duration_days is None else cint(self.rental_duration_days)
            if days <= 0:
                frappe.throw("يجب أن تكون مدة التأجير يوماً واحداً على الأقل.")
            self.rental_duration_days = days
            
            # حساب تاريخ الاستحقاق (تاريخ اليوم + عدد الأيام)
            transaction_date = getdate(self.date) if self.date else getdate()
            self.due_date = add_days(transaction_date, days)
            
            # حساب رسوم التأجير والإجمالي
            self.rental_fee = days * rental_rate
            self.total_amount = (self.rental_fee or 0) + (self.late_fee or 0)

    def on_submit(self):
        """عند الضغط على Submit لترحيل المعاملة"""
        if self.type == "Issue":
            frappe.db.set_value("Article", self.article, "status", "Issued")
        elif self.type == "Return":
            frappe.db.set_value("Article", self.article, "status", "Available")
        self.update_member_debt()

    def before_update_after_submit(self):
        frappe.get_doc("Library Member", self.library_member, for_update=True)
        if self.type != "Issue":
            frappe.throw("يتم تحديث المدفوعات على معاملة الاستعارة الأصلية.")
        if flt(self.late_fee) < 0:
            frappe.throw("لا يمكن أن تكون رسوم التأخير سالبة.")
        self.total_amount = flt(self.rental_fee) + flt(self.late_fee)

    def on_update_after_submit(self):
        self.update_member_debt()

    def update_member_debt(self):
        unpaid = frappe.get_all(
            "Library Transaction",
            filters={"library_member": self.library_member, "type": "Issue", "docstatus": 1},
            fields=["total_amount", "payment_status"],
        )
        debt = sum(flt(row.total_amount) for row in unpaid if row.payment_status not in ("Paid", "Refunded"))
        frappe.db.set_value("Library Member", self.library_member, "outstanding_debt", debt)

    def before_cancel(self):
        frappe.get_doc("Library Member", self.library_member, for_update=True)
        article = frappe.get_doc("Article", self.article, for_update=True)
        transactions = frappe.get_all(
            "Library Transaction",
            filters={"article": self.article, "docstatus": 1},
            fields=["name"],
            order_by="submitted_on desc, creation desc",
            limit_page_length=1,
        )
        expected_status = "Issued" if self.type == "Issue" else "Available"
        if not transactions or transactions[0].name != self.name or article.status != expected_status:
            frappe.throw("يجب إلغاء المعاملات الأحدث لهذا الكتاب أولاً.")

    def on_cancel(self):
        status = "Available" if self.type == "Issue" else "Issued"
        frappe.db.set_value("Article", self.article, "status", status)
        self.update_member_debt()
