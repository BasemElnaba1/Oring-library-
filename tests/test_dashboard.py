from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from library_management import dashboard
from library_management.oring_libarary.doctype.article.article import create_rental_request


class TestOwnerDashboard(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("owner_dashboard_test")
		self.addCleanup(frappe.db.rollback, save_point="owner_dashboard_test")
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=10)
		self.member = frappe.get_doc(
			{
				"doctype": "Library Member",
				"first_name": f"Owner Test {suffix}",
				"email": f"owner-test-{suffix}@example.invalid",
				"max_active_rentals": 1,
			}
		).insert()
		self.book = frappe.get_doc(
			{
				"doctype": "Article",
				"title": f"Owner Book {suffix}",
				"status": "Available",
				"is_rentable": 1,
				"rental_rate_per_day": 5,
			}
		).insert()

	def request(self):
		with patch.dict(frappe.session, {"user": self.member.email}):
			return create_rental_request(self.book.name)

	def issue(self, **values):
		return dashboard.issue_book(self.book.name, self.member.name, **values)

	def test_guests_and_borrowers_cannot_read_or_mutate(self):
		for user in ("Guest", self.member.email):
			with (
				patch.dict(frappe.session, {"user": user}),
				patch("frappe.get_roles", return_value=["Website User"]),
			):
				self.assertFalse(dashboard.can_manage_library())
				with self.assertRaises(frappe.PermissionError):
					dashboard.get_dashboard()
				with self.assertRaises(frappe.PermissionError):
					self.issue()
		self.assertFalse(frappe.db.exists("Library Transaction", {"article": self.book.name}))

	def test_pending_requests_are_not_income(self):
		before = dashboard.get_dashboard()
		name = self.request()
		after = dashboard.get_dashboard()
		self.assertIn(name, [row["name"] for row in after["pending_requests"]])
		self.assertEqual(after["summary"]["pending"], before["summary"]["pending"] + 1)
		self.assertEqual(after["summary"]["billed"], before["summary"]["billed"])
		self.assertEqual(after["summary"]["outstanding"], before["summary"]["outstanding"])

	def test_approval_records_debt_and_revalidates_competing_request(self):
		name = self.request()
		competing = frappe.copy_doc(frappe.get_doc("Library Transaction", name)).insert()
		dashboard.approve_request(name, rental_duration_days=4)
		doc = frappe.get_doc("Library Transaction", name)
		self.assertEqual(doc.request_status, "Approved")
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.total_amount, 20)
		self.assertTrue(doc.submitted_on)
		self.assertEqual(frappe.db.get_value("Library Member", self.member.name, "outstanding_debt"), 20)
		with self.assertRaises(frappe.ValidationError):
			dashboard.approve_request(competing.name)
		self.assertEqual(frappe.db.get_value("Library Transaction", competing.name, "docstatus"), 0)

	def test_rejection_allows_a_new_request_and_keeps_reason(self):
		name = self.request()
		dashboard.reject_request(name, "Requested dates unavailable")
		doc = frappe.get_doc("Library Transaction", name)
		self.assertEqual(doc.request_status, "Rejected")
		self.assertEqual(doc.rejection_reason, "Requested dates unavailable")
		self.assertNotIn(name, [row["name"] for row in dashboard.get_dashboard()["pending_requests"]])
		self.assertNotEqual(self.request(), name)
		with self.assertRaises(frappe.ValidationError):
			dashboard.approve_request(name)

	def test_payment_preserves_original_rate_and_updates_balance(self):
		name = self.issue(rental_duration_days=4)
		self.book.db_set("rental_rate_per_day", 100)
		result = dashboard.update_payment(name, "Unpaid", late_fee=3)
		self.assertEqual(result["total_amount"], 23)
		self.assertEqual(frappe.db.get_value("Library Transaction", name, "rental_fee"), 20)
		self.assertEqual(frappe.db.get_value("Library Member", self.member.name, "outstanding_debt"), 23)
		dashboard.update_payment(name, "Paid")
		self.assertEqual(frappe.db.get_value("Library Member", self.member.name, "outstanding_debt"), 0)
		with self.assertRaises(frappe.ValidationError):
			dashboard.update_payment(name, "Paid", late_fee=-1)
		with self.assertRaises(frappe.ValidationError):
			dashboard.update_payment(name, "Invalid")

	def test_stale_request_can_be_rejected_after_book_becomes_unavailable(self):
		name = self.request()
		self.book.db_set("status", "Issued")
		dashboard.reject_request(name, "Book unavailable")
		self.assertEqual(frappe.db.get_value("Library Transaction", name, "request_status"), "Rejected")
		self.assertEqual(frappe.db.get_value("Article", self.book.name, "status"), "Issued")

	def test_return_links_issue_prevents_duplicates_and_keeps_unpaid_debt(self):
		name = self.issue(rental_duration_days=2)
		returned = dashboard.return_book(name)
		self.assertEqual(frappe.db.get_value("Library Transaction", returned, "reference_issue"), name)
		self.assertEqual(frappe.db.get_value("Article", self.book.name, "status"), "Available")
		self.assertEqual(frappe.db.get_value("Library Member", self.member.name, "outstanding_debt"), 10)
		self.assertNotIn(name, [row["name"] for row in dashboard.get_dashboard()["active_rentals"]])
		with self.assertRaises(frappe.ValidationError):
			dashboard.return_book(name)
		self.issue()

	def test_overdue_uses_due_date_and_payment_list_ignores_report_period(self):
		name = self.issue(date=add_days(today(), -10), rental_duration_days=2)
		snapshot = dashboard.get_dashboard(from_date=add_days(today(), -100), to_date=add_days(today(), -90))
		row = next(row for row in snapshot["active_rentals"] if row["name"] == name)
		self.assertEqual(row["overdue_days"], 8)
		self.assertIn(name, [row["name"] for row in snapshot["payments"]])
		self.assertEqual(snapshot["summary"]["billed"], 0)

	def test_suspend_blocks_issues_and_reactivate_restores_access(self):
		dashboard.set_member_suspended(self.member.name, 1)
		with self.assertRaises(frappe.ValidationError):
			self.issue()
		dashboard.set_member_suspended(self.member.name, 0)
		self.issue()

	def test_owner_forms_validate_inputs_and_ignore_protected_fields(self):
		dashboard.save_book({"title": "Updated Owner Book", "status": "Issued"}, name=self.book.name)
		self.assertEqual(frappe.db.get_value("Article", self.book.name, "status"), "Available")
		with self.assertRaises(frappe.ValidationError):
			dashboard.save_book({"rental_rate_per_day": -1}, name=self.book.name)
		with self.assertRaises(frappe.ValidationError):
			dashboard.save_member({"max_active_rentals": 0}, name=self.member.name)
		with self.assertRaises(frappe.ValidationError):
			dashboard.get_dashboard(from_date=today(), to_date=add_days(today(), -1))
