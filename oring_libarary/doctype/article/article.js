frappe.ui.form.on('Article', {
    refresh(frm) {
        if (frm.doc.status === 'Available') {
            frm.add_custom_button(__('طلب تأجير'), function() {
                frappe.call({
                    method: 'library_management.oring_libarary.doctype.article.article.create_rental_request',
                    args: {
                        article: frm.doc.name
                    },
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.msgprint(__('تم تقديم طلب التأجير بنجاح!'));
                            frm.reload_doc();
                        }
                    }
                });
            });
        }
    }
});
