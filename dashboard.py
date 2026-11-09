"""Owner reporting and actions, using the same documents as Frappe Desk."""

import json
from collections import Counter
from datetime import timedelta
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, today, validate_email_address


def can_manage_library():
	user = frappe.session.user
	return user != "Guest" and (user == "Administrator" or "System Manager" in frappe.get_roles(user))


def require_owner():
	if not can_manage_library():
		frappe.throw(_("This dashboard is restricted to library managers."), frappe.PermissionError)
	for doctype in ("Article", "Library Member", "Library Transaction"):
		frappe.has_permission(doctype, "read", throw=True)


def _form_url(doctype, name):
	return f"/app/{doctype.lower().replace(' ', '-')}/{quote(name, safe='')}"


def _lock_transaction(name):
	require_owner()
	links = frappe.db.get_value("Library Transaction", name, ["library_member", "article"], as_dict=True)
	if not links:
		frappe.throw(_("Rental transaction not found."), frappe.DoesNotExistError)
	frappe.get_doc("Library Member", links.library_member, for_update=True)
	frappe.get_doc("Article", links.article, for_update=True)
	doc = frappe.get_doc("Library Transaction", name, for_update=True)
	doc.check_permission("write")
	if doc.library_member != links.library_member or doc.article != links.article:
		frappe.throw(_("The transaction changed. Refresh and try again."))
	return doc


def _check_pending(doc):
	if doc.type != "Issue" or doc.docstatus != 0 or doc.request_status == "Rejected":
		frappe.throw(_("Only pending issue requests can be reviewed."))


def _issue_days(value):
	if cint(value) <= 0 or flt(value) != cint(value):
		frappe.throw(_("Rental duration must be a positive whole number of days."))
	return cint(value)


def _issue_date(value):
	date = getdate(value or today())
	if date > getdate(today()):
		frappe.throw(_("An issue date cannot be in the future."))
	return date


@frappe.whitelist(methods=["POST"])
def approve_request(name, date=None, rental_duration_days=None):
	doc = _lock_transaction(name)
	_check_pending(doc)
	doc.date = _issue_date(date)
	doc.rental_duration_days = _issue_days(
		rental_duration_days if rental_duration_days is not None else (doc.rental_duration_days or 7)
	)
	doc.submit()
	return doc.name


@frappe.whitelist(methods=["POST"])
def reject_request(name, reason):
	doc = _lock_transaction(name)
	_check_pending(doc)
	if not isinstance(reason, str) or not reason.strip():
		frappe.throw(_("Please provide a rejection reason."))
	doc.date = doc.date or getdate(doc.creation)
	doc.request_status = "Rejected"
	doc.rejection_reason = reason.strip()
	doc.save()
	return doc.name


@frappe.whitelist(methods=["POST"])
def issue_book(article, library_member, rental_duration_days=7, date=None):
	require_owner()
	frappe.get_doc("Library Member", library_member, for_update=True).check_permission("read")
	frappe.get_doc("Article", article, for_update=True).check_permission("read")
	doc = frappe.get_doc(
		{
			"doctype": "Library Transaction",
			"article": article,
			"library_member": library_member,
			"type": "Issue",
			"date": _issue_date(date),
			"rental_duration_days": _issue_days(rental_duration_days),
		}
	)
	doc.insert()
	doc.submit()
	return doc.name


@frappe.whitelist(methods=["POST"])
def return_book(name, date=None):
	issue = _lock_transaction(name)
	if issue.type != "Issue" or issue.docstatus != 1:
		frappe.throw(_("Select a confirmed issue transaction."))
	if frappe.db.exists(
		"Library Transaction", {"reference_issue": issue.name, "type": "Return", "docstatus": 1}
	):
		frappe.throw(_("This rental has already been returned."))
	return_date = getdate(date or today())
	if return_date < getdate(issue.date) or return_date > getdate(today()):
		frappe.throw(_("The return date must be between the issue date and today."))
	doc = frappe.get_doc(
		{
			"doctype": "Library Transaction",
			"article": issue.article,
			"library_member": issue.library_member,
			"type": "Return",
			"date": return_date,
			"reference_issue": issue.name,
		}
	)
	doc.insert()
	doc.submit()
	return doc.name


@frappe.whitelist(methods=["POST"])
def update_payment(name, payment_status, late_fee=None):
	doc = _lock_transaction(name)
	if doc.type != "Issue" or doc.docstatus != 1:
		frappe.throw(_("Payments can only be recorded against confirmed rentals."))
	if payment_status not in ("Unpaid", "Paid", "Refunded"):
		frappe.throw(_("Invalid payment status."))
	if late_fee is not None:
		if flt(late_fee) < 0:
			frappe.throw(_("Late fees cannot be negative."))
		doc.late_fee = flt(late_fee)
	doc.payment_status = payment_status
	doc.save()
	return {"name": doc.name, "total_amount": doc.total_amount, "payment_status": doc.payment_status}


@frappe.whitelist(methods=["POST"])
def set_member_suspended(name, suspended):
	require_owner()
	doc = frappe.get_doc("Library Member", name, for_update=True)
	doc.check_permission("write")
	if str(suspended) not in ("0", "1"):
		frappe.throw(_("Invalid member status."))
	doc.is_suspended = cint(suspended)
	doc.save()
	return doc.name


def _object(values):
	values = frappe.parse_json(values)
	if not isinstance(values, dict):
		frappe.throw(_("Invalid form values."))
	return values


@frappe.whitelist(methods=["POST"])
def save_book(values, name=None):
	require_owner()
	values = _object(values)
	doc = frappe.get_doc("Article", name, for_update=True) if name else frappe.new_doc("Article")
	if name:
		doc.check_permission("write")
	for field in (
		"title",
		"author",
		"ispn",
		"image",
		"description",
		"rental_rate_per_day",
		"security_deposit",
		"is_rentable",
	):
		if field in values:
			setattr(doc, field, values[field])
	if not isinstance(doc.title, str) or not doc.title.strip():
		frappe.throw(_("A book title is required."))
	if flt(doc.rental_rate_per_day) < 0 or flt(doc.security_deposit) < 0:
		frappe.throw(_("Rental rates and deposits cannot be negative."))
	if not name:
		doc.status = "Available"
	doc.save()
	return doc.name


@frappe.whitelist(methods=["POST"])
def save_member(values, name=None):
	require_owner()
	values = _object(values)
	doc = (
		frappe.get_doc("Library Member", name, for_update=True) if name else frappe.new_doc("Library Member")
	)
	if name:
		doc.check_permission("write")
	for field in ("first_name", "last_name", "email", "phone", "max_active_rentals"):
		if field in values:
			setattr(doc, field, values[field])
	if not isinstance(doc.first_name, str) or not doc.first_name.strip():
		frappe.throw(_("A member's first name is required."))
	if not doc.email:
		frappe.throw(_("A member email is required."))
	doc.email = validate_email_address(doc.email, throw=True)
	doc.max_active_rentals = _issue_days(3 if doc.max_active_rentals is None else doc.max_active_rentals)
	doc.save()
	return doc.name


@frappe.whitelist(methods=["GET", "POST"])
def get_dashboard(from_date=None, to_date=None):
	require_owner()
	end = getdate(to_date or today())
	start = getdate(from_date or add_days(end, -29))
	if start > end:
		frappe.throw(_("The start date must be on or before the end date."))
	if date_diff(end, start) > 366:
		frappe.throw(_("Please select a reporting period of up to one year."))
	books = frappe.get_list(
		"Article",
		fields=[
			"name",
			"title",
			"author",
			"ispn",
			"image",
			"description",
			"route",
			"status",
			"is_rentable",
			"rental_rate_per_day",
			"security_deposit",
		],
		limit_page_length=0,
		order_by="title asc",
	)
	members = frappe.get_list(
		"Library Member",
		fields=[
			"name",
			"first_name",
			"last_name",
			"email",
			"phone",
			"is_suspended",
			"max_active_rentals",
			"outstanding_debt",
		],
		limit_page_length=0,
		order_by="first_name asc",
	)
	transactions = frappe.get_list(
		"Library Transaction",
		fields=[
			"name",
			"article",
			"library_member",
			"type",
			"docstatus",
			"date",
			"due_date",
			"rental_duration_days",
			"rental_fee",
			"late_fee",
			"total_amount",
			"payment_status",
			"request_status",
			"rejection_reason",
			"reference_issue",
			"submitted_on",
			"creation",
		],
		limit_page_length=0,
		order_by="creation desc",
	)
	book_map = {book.name: book for book in books}
	member_map = {member.name: member for member in members}
	returned = {
		row.reference_issue
		for row in transactions
		if row.type == "Return" and row.docstatus == 1 and row.reference_issue
	}
	issues = [row for row in transactions if row.type == "Issue" and row.docstatus == 1]
	active = [row for row in issues if row.name not in returned]
	pending = [
		row
		for row in transactions
		if row.type == "Issue" and row.docstatus == 0 and row.request_status != "Rejected"
	]
	current_date = getdate(today())
	for row in transactions:
		book = book_map.get(row.article, {})
		member = member_map.get(row.library_member, {})
		row.book_title = book.get("title") or row.article
		row.member_name = (
			" ".join(filter(None, [member.get("first_name"), member.get("last_name")])) or row.library_member
		)
		row.payment_status = row.payment_status or "Unpaid"
		row.overdue_days = (
			max(0, date_diff(current_date, row.due_date))
			if row.due_date and row.name not in returned and row.docstatus == 1 and row.type == "Issue"
			else 0
		)
		row.form_url = _form_url("Library Transaction", row.name)
		row.rental_state = (
			"Cancelled"
			if row.docstatus == 2
			else "Returned"
			if (row.type == "Return" and row.docstatus == 1) or row.name in returned
			else "Active"
			if row.docstatus == 1
			else "Rejected"
			if row.request_status == "Rejected"
			else "Pending"
		)
	for book in books:
		book.form_url = _form_url("Article", book.name)
	for member in members:
		member.display_name = " ".join(filter(None, [member.first_name, member.last_name])) or member.name
		member.form_url = _form_url("Library Member", member.name)
		member.active_rentals = sum(1 for row in active if row.library_member == member.name)
		member.pending_requests = sum(1 for row in pending if row.library_member == member.name)
		member.balance = sum(
			flt(row.total_amount)
			for row in issues
			if row.library_member == member.name and row.payment_status == "Unpaid"
		)

	period_issues = [
		row for row in issues if start <= getdate(row.submitted_on or row.date or row.creation) <= end
	]
	months = {}
	cursor = start.replace(day=1)
	while cursor <= end:
		months[cursor.strftime("%Y-%m")] = {"billed": 0, "paid": 0}
		cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
	for row in period_issues:
		key = getdate(row.submitted_on or row.date or row.creation).strftime("%Y-%m")
		months[key]["billed"] += flt(row.total_amount)
		if row.payment_status == "Paid":
			months[key]["paid"] += flt(row.total_amount)

	active_by_book = {row.article: row for row in active}
	alerts = []
	for book in books:
		if book.status == "Issued" and book.name not in active_by_book:
			alerts.append(
				{"message": f"الكتاب «{book.title}» مستعار دون معاملة مؤكدة مرتبطة به.", "url": book.form_url}
			)
		elif book.status != "Issued" and book.name in active_by_book:
			alerts.append(
				{
					"message": f"حالة الكتاب «{book.title}» لا تطابق معاملة الاستعارة النشطة.",
					"url": book.form_url,
				}
			)
	duplicate_requests = Counter((row.article, row.library_member) for row in pending)
	for (article, member), count in duplicate_requests.items():
		if count > 1:
			row = next(row for row in pending if row.article == article and row.library_member == member)
			alerts.append(
				{
					"message": f"يوجد {count} طلبات معلقة لنفس الكتاب والعضو: {row.book_title} — {row.member_name}.",
					"url": row.form_url,
				}
			)
	for member in members:
		if not member.email or not frappe.db.exists("User", {"name": member.email, "enabled": 1}):
			alerts.append(
				{
					"message": f"العضو «{member.display_name}» لا يرتبط بحساب دخول مفعّل بنفس البريد.",
					"url": member.form_url,
				}
			)
	for row in transactions:
		if row.type == "Return" and row.docstatus == 1 and not row.reference_issue:
			alerts.append(
				{
					"message": f"معاملة الإرجاع {row.name} تحتاج ربطاً بمعاملة الاستعارة الأصلية.",
					"url": row.form_url,
				}
			)

	inventory = Counter(
		"Issued"
		if book.status == "Issued"
		else "Display"
		if not book.is_rentable
		else "Available"
		if book.status == "Available"
		else "Unknown"
		for book in books
	)
	result = {
		"today": today(),
		"currency": "EGP",
		"timezone": frappe.get_system_settings("time_zone"),
		"filters": {"from_date": start, "to_date": end},
		"summary": {
			"books": len(books),
			"members": len(members),
			"available": inventory["Available"],
			"issued": inventory["Issued"],
			"pending": len(pending),
			"active": len(active),
			"overdue": sum(row.overdue_days > 0 for row in active),
			"billed": sum(flt(row.total_amount) for row in period_issues),
			"paid": sum(flt(row.total_amount) for row in period_issues if row.payment_status == "Paid"),
			"refunded": sum(
				flt(row.total_amount) for row in period_issues if row.payment_status == "Refunded"
			),
			"outstanding": sum(flt(row.total_amount) for row in issues if row.payment_status == "Unpaid"),
		},
		"inventory": dict(inventory),
		"monthly": [{"month": month, **values} for month, values in months.items()],
		"books": books,
		"members": members,
		"pending_requests": pending,
		"active_rentals": active,
		"payments": issues,
		"history": transactions[:100],
		"alerts": alerts,
	}
	return json.loads(frappe.as_json(result))
