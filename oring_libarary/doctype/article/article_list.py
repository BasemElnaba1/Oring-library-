import frappe

def get_context(context):
    context.parents = [{"name": "Home", "route": "/"}]