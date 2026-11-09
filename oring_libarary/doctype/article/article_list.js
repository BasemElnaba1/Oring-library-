frappe.listview_settings['Article'] = {
    add_fields: ["status"],
    get_indicator(doc) {
        if (doc.status === "Available") {
            return [__("Available"), "green", "status,=,Available"];
        } else if (doc.status === "Issued") {
            return [__("Issued"), "red", "status,=,Issued"];
        }
    }
};