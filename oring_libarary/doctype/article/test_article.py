# Copyright (c) 2026, Basem elnaba  and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from library_management.oring_libarary.doctype.article.article import create_rental_request


class TestArticle(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("rental_request_test")
		self.addCleanup(frappe.db.rollback, save_point="rental_request_test")
		suffix = frappe.generate_hash(length=10)
		self.email = f"rental-{suffix}@example.invalid"
		self.member = frappe.get_doc({
			"doctype": "Library Member",
			"first_name": f"Rental Test {suffix}",
			"email": self.email,
		}).insert(ignore_permissions=True)
		self.article = frappe.get_doc({
			"doctype": "Article",
			"title": f"Rental Test {suffix}",
			"status": "Available",
			"is_rentable": 1,
			"rental_rate_per_day": 5,
		}).insert(ignore_permissions=True)
		user = patch.dict(frappe.session, {"user": self.email})
		user.start()
		self.addCleanup(user.stop)

	def test_member_can_request_available_book(self):
		name = create_rental_request(self.article.name)
		transaction = frappe.get_doc("Library Transaction", name)
		self.assertEqual(transaction.library_member, self.member.name)
		self.assertEqual(transaction.article, self.article.name)
		self.assertEqual(transaction.type, "Issue")
		self.assertEqual(transaction.docstatus, 0)
		self.assertEqual(transaction.rental_duration_days, 7)
		self.assertEqual(transaction.rental_fee, 35)
		self.assertEqual(transaction.total_amount, 35)
		self.assertEqual(str(transaction.due_date), add_days(today(), 7))
		self.assertEqual(frappe.db.get_value("Article", self.article.name, "status"), "Available")

	def assert_request_rejected(self, message):
		with self.assertRaisesRegex(frappe.ValidationError, message):
			create_rental_request(self.article.name)
		self.assertFalse(frappe.db.exists("Library Transaction", {"article": self.article.name}))

	def test_guest_must_log_in(self):
		with patch.dict(frappe.session, {"user": "Guest"}):
			self.assert_request_rejected("يرجى تسجيل الدخول")

	def test_unregistered_user_cannot_request(self):
		with patch.dict(frappe.session, {"user": "unregistered@example.invalid"}):
			self.assert_request_rejected("غير مسجل كعضو")

	def test_issued_book_cannot_be_requested(self):
		self.article.db_set("status", "Issued")
		self.assert_request_rejected("غير متاح للتأجير")

	def test_suspended_member_cannot_request(self):
		self.member.db_set("is_suspended", 1)
		self.assert_request_rejected("محظور")

	def test_display_only_book_cannot_be_requested(self):
		self.article.db_set("is_rentable", 0)
		self.assert_request_rejected("للعرض فقط")

	def test_duplicate_request_is_rejected(self):
		name = create_rental_request(self.article.name)
		with self.assertRaisesRegex(frappe.ValidationError, "طلب تأجير معلق"):
			create_rental_request(self.article.name)
		self.assertEqual(
			frappe.get_all("Library Transaction", filters={"article": self.article.name}, pluck="name"),
			[name],
		)
