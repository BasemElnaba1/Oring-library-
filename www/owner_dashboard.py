"""Private website entry point for the owner dashboard."""

import frappe

from library_management.dashboard import get_dashboard, require_owner

no_cache = True
sitemap = False


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=%2Fowner-dashboard"
		raise frappe.Redirect
	require_owner()
	context.dashboard = get_dashboard()
	context.title = "لوحة إدارة المكتبة"
	context.no_cache = True
