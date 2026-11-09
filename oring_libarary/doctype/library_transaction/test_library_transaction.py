# Copyright (c) 2026, Basem elnaba  and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestLibraryTransaction(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("rental_lifecycle_test")
		self.addCleanup(frappe.db.rollback, save_point="rental_lifecycle_test")
		suffix = frappe.generate_hash(length=10)
		self.member = frappe.get_doc({
			"doctype": "Library Member",
			"first_name": f"Lifecycle Test {suffix}",
			"email": f"lifecycle-{suffix}@example.invalid",
			"max_active_rentals": 1,
		}).insert()
		self.article = self.make_article(suffix)

	def make_article(self, suffix):
		return frappe.get_doc({
			"doctype": "Article",
			"title": f"Lifecycle Book {suffix}",
			"status": "Available",
			"is_rentable": 1,
			"rental_rate_per_day": 5,
		}).insert()

	def make_transaction(self, kind="Issue", **values):
		return frappe.get_doc({
			"doctype": "Library Transaction",
			"article": self.article.name,
			"library_member": self.member.name,
			"type": kind,
			**values,
		}).insert()

	def assert_article_status(self, status):
		self.assertEqual(frappe.db.get_value("Article", self.article.name, "status"), status)

	def test_issue_and_return_update_availability(self):
		issue = self.make_transaction().submit()
		self.assertEqual(issue.docstatus, 1)
		self.assert_article_status("Issued")
		self.make_transaction("Return").submit()
		self.assert_article_status("Available")
		self.make_transaction().submit()
		self.assert_article_status("Issued")

	def test_issue_cancellation_restores_availability(self):
		self.make_transaction().submit().cancel()
		self.assert_article_status("Available")

	def test_return_cancellation_restores_issue(self):
		self.make_transaction().submit()
		self.make_transaction("Return").submit().cancel()
		self.assert_article_status("Issued")

	def test_old_issue_cannot_be_cancelled_after_return(self):
		issue = self.make_transaction().submit()
		self.make_transaction("Return").submit()
		with self.assertRaisesRegex(frappe.ValidationError, "المعاملات الأحدث"):
			issue.cancel()
		self.assert_article_status("Available")

	def test_available_book_cannot_be_returned(self):
		with self.assertRaisesRegex(frappe.ValidationError, "غير مستعار"):
			self.make_transaction("Return")

	def test_member_rental_limit_is_enforced(self):
		self.make_transaction().submit()
		other = self.make_article(frappe.generate_hash(length=10))
		with self.assertRaisesRegex(frappe.ValidationError, "الحد الأقصى"):
			self.make_transaction(article=other.name)

	def test_draft_is_revalidated_before_submission(self):
		draft = self.make_transaction()
		self.member.db_set("is_suspended", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "محظور"):
			draft.submit()
		self.assert_article_status("Available")

	def test_invalid_rental_duration_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "مدة التأجير"):
			self.make_transaction(rental_duration_days=0)
