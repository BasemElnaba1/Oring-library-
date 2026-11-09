import frappe
from frappe.website.website_generator import WebsiteGenerator

class Article(WebsiteGenerator):
    no_cache = True

@frappe.whitelist(allow_guest=True, methods=["POST"])
def create_rental_request(article):
    # 1. التحقق من تسجيل الدخول
    if frappe.session.user == "Guest":
        frappe.throw(
            msg="يرجى تسجيل الدخول أولاً للتمكن من استعارة الكتاب.",
            title="تسجيل الدخول مطلوب"
        )

    # 2. البحث عن العضو المرتبط بالحساب الحالي
    member = frappe.db.get_value("Library Member", {"email": frappe.session.user}, "name")

    if not member:
        frappe.throw(
            msg="حسابك غير مسجل كعضو في المكتبة. يرجى التواصل مع الإدارة لربط بريد حسابك بعضويتك.",
            title="عضوية غير مفعّلة"
        )

    # 3. التحقق من وجود الكتاب وحالته
    # Serialize requests from the same member and book so double clicks cannot
    # create duplicate drafts. These locks are released by Frappe's transaction.
    frappe.get_doc("Library Member", member, for_update=True)
    if not frappe.db.exists("Article", article):
        frappe.throw("الكتاب المطلوب غير موجود في النظام.")
    book = frappe.get_doc("Article", article, for_update=True)
    if book.status != "Available":
        frappe.throw("عذراً، هذا الكتاب غير متاح للتأجير حالياً.")

    # 4. منع التكرار: التحقق مما إذا كان هناك طلب معلق لنفس الكتاب من نفس العضو
    requests = frappe.get_all("Library Transaction", filters={
        "article": article,
        "library_member": member,
        "type": "Issue",
        "docstatus": 0
    }, fields=["name", "request_status"])
    
    if any(request.request_status != "Rejected" for request in requests):
        frappe.throw("لديك طلب تأجير معلق بالفعل لهذا الكتاب بانتظار موافقة الإدارة.")

    # 5. إنشاء المعاملة وتسجيلها
    transaction = frappe.get_doc({
        "doctype": "Library Transaction",
        "article": article,
        "library_member": member,
        "type": "Issue",
        "date": frappe.utils.today()
    })
    
    transaction.insert(ignore_permissions=True)

    return transaction.name
