frappe.ready(function () {
	const root = document.getElementById("owner-dashboard");
	if (!root) return;
	const initial = JSON.parse(document.getElementById("owner-dashboard-data").textContent);
	const api = "library_management.dashboard.";
	const escape = (value) =>
		String(value ?? "").replace(
			/[&<>"']/g,
			(char) =>
				({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
		);
	const money = (value) =>
		`<bdi dir="ltr">EGP ${Number(value || 0).toLocaleString("en-US", {
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		})}</bdi>`;
	const date = (value) =>
		value ? escape(frappe.datetime.str_to_user(value.slice(0, 10))) : "—";
	const badge = (label, kind = "") =>
		`<span class="owner-dashboard-badge ${kind}">${escape(label)}</span>`;
	const paymentLabels = { Unpaid: "غير مدفوع", Paid: "مدفوع", Refunded: "مُستردّ" };
	const stateLabels = {
		Pending: "بانتظار المراجعة",
		Rejected: "مرفوض",
		Active: "نشط",
		Returned: "تم الإرجاع",
		Cancelled: "ملغى",
	};
	const control = (id, df) =>
		frappe.ui.form.make_control({
			parent: document.getElementById(id),
			df,
			render_input: true,
		});
	const call = (method, args) =>
		new Promise((resolve, reject) =>
			frappe.call({
				method: api + method,
				args,
				freeze: true,
				callback: (response) =>
					response.exc ? reject(response) : resolve(response.message),
				error: reject,
			}),
		);
	let data = initial;
	let refreshing = false;
	let activeTab = "requests";
	const status = document.getElementById("owner-dashboard-status");
	const fromDate = control("owner-from-date", {
		fieldtype: "Date",
		fieldname: "from_date",
		label: "من تاريخ",
		reqd: 1,
		default: data.filters.from_date,
	});
	const toDate = control("owner-to-date", {
		fieldtype: "Date",
		fieldname: "to_date",
		label: "إلى تاريخ",
		reqd: 1,
		default: data.filters.to_date,
	});
	const search = control("owner-search", {
		fieldtype: "Data",
		fieldname: "search",
		label: "بحث",
		placeholder: "كتاب، عضو، أو رقم معاملة",
	});
	const bookStatus = control("owner-book-status", {
		fieldtype: "Select",
		fieldname: "book_status",
		label: "حالة الكتاب",
		options: [
			{ label: "جميع الكتب", value: "" },
			{ label: "متاح", value: "Available" },
			{ label: "مستعار", value: "Issued" },
			{ label: "للعرض فقط", value: "Display" },
		],
	});
	fromDate.set_value(data.filters.from_date);
	toDate.set_value(data.filters.to_date);
	const action = (name, label, row, outline = false) =>
		`<button type="button" class="owner-dashboard-action ${
			outline ? "is-outline" : ""
		}" data-action="${name}" data-name="${escape(row.name)}">${label}</button>`;
	const recordLink = (row, label) =>
		`<a class="owner-dashboard-record-link" href="${escape(row.form_url)}">${escape(
			label,
		)}</a>`;
	const find = (name) =>
		[...data.pending_requests, ...data.active_rentals, ...data.payments, ...data.history].find(
			(row) => row.name === name,
		);
	const matches = (row) => {
		const query = (search.$input.val() || "").trim().toLocaleLowerCase();
		return (
			!query ||
			[
				row.name,
				row.book_title,
				row.title,
				row.author,
				row.member_name,
				row.display_name,
				row.email,
				row.phone,
			]
				.join(" ")
				.toLocaleLowerCase()
				.includes(query)
		);
	};
	function table(id, rows, columns, emptyLabel) {
		const host = document.getElementById("owner-table-" + id);
		const filtered = rows.filter(matches);
		if (!filtered.length) {
			host.innerHTML = `<p class="owner-dashboard-empty">${emptyLabel}</p>`;
			return;
		}
		host.innerHTML = `<table class="owner-dashboard-table"><thead><tr>${columns
			.map((col) => `<th scope="col">${col.label}</th>`)
			.join("")}</tr></thead><tbody>${filtered
			.map(
				(row) =>
					`<tr>${columns.map((col) => `<td>${col.render(row)}</td>`).join("")}</tr>`,
			)
			.join("")}</tbody></table>`;
	}
	function blocker(row) {
		const book = data.books.find((book) => book.name === row.article);
		const member = data.members.find((member) => member.name === row.library_member);
		if (!book || !book.is_rentable || book.status !== "Available")
			return "الكتاب غير متاح للاعتماد حالياً";
		if (!member || member.is_suspended) return "العضوية موقوفة";
		if (member.active_rentals >= (member.max_active_rentals || 3))
			return "وصل العضو إلى حد الاستعارة";
		return "";
	}
	function renderTables() {
		table(
			"requests",
			data.pending_requests,
			[
				{
					label: "الكتاب",
					render: (row) =>
						`${escape(row.book_title)}${
							blocker(row)
								? `<small class="owner-dashboard-cell-note">${blocker(
										row,
									)}</small>`
								: ""
						}`,
				},
				{ label: "العضو", render: (row) => escape(row.member_name) },
				{ label: "تاريخ الطلب", render: (row) => date(row.creation) },
				{ label: "المدة", render: (row) => `${row.rental_duration_days || 7} أيام` },
				{ label: "قيمة الطلب", render: (row) => money(row.total_amount) },
				{
					label: "الإجراء",
					render: (row) =>
						`<div class="owner-dashboard-row-actions">${
							!blocker(row) ? action("approve", "اعتماد", row) : ""
						}${action("reject", "رفض", row, true)}${recordLink(row, "السجل")}</div>`,
				},
			],
			"لا توجد طلبات معلقة مطابقة.",
		);
		table(
			"rentals",
			data.active_rentals,
			[
				{ label: "الكتاب", render: (row) => escape(row.book_title) },
				{ label: "العضو", render: (row) => escape(row.member_name) },
				{
					label: "موعد الإرجاع",
					render: (row) =>
						`${date(row.due_date)}${
							row.overdue_days
								? `<small class="owner-dashboard-cell-note is-overdue">متأخر ${row.overdue_days} يوم</small>`
								: ""
						}`,
				},
				{ label: "الإجمالي", render: (row) => money(row.total_amount) },
				{
					label: "الدفع",
					render: (row) =>
						badge(
							paymentLabels[row.payment_status],
							row.payment_status === "Paid" ? "is-green" : "is-amber",
						),
				},
				{
					label: "الإجراء",
					render: (row) =>
						`<div class="owner-dashboard-row-actions">${action(
							"return",
							"تسجيل الإرجاع",
							row,
						)}${action("payment", "الدفع", row, true)}</div>`,
				},
			],
			"لا توجد استعارات نشطة مطابقة.",
		);
		const selectedStatus = bookStatus.get_value();
		const books = data.books.filter(
			(book) =>
				!selectedStatus ||
				(selectedStatus === "Display"
					? !book.is_rentable
					: book.status === selectedStatus),
		);
		table(
			"books",
			books,
			[
				{
					label: "الكتاب",
					render: (row) =>
						`${recordLink(
							row,
							row.title,
						)}<small class="owner-dashboard-cell-note">${escape(
							row.author || "غير محدد",
						)}</small>`,
				},
				{
					label: "الحالة",
					render: (row) =>
						badge(
							row.status === "Issued"
								? "مستعار"
								: row.is_rentable
									? row.status === "Available"
										? "متاح"
										: "حالة غير محددة"
									: "للعرض فقط",
							row.status === "Issued" ? "is-amber" : "is-green",
						),
				},
				{ label: "سعر اليوم", render: (row) => money(row.rental_rate_per_day) },
				{ label: "التأمين", render: (row) => money(row.security_deposit) },
				{
					label: "الإجراء",
					render: (row) =>
						`<div class="owner-dashboard-row-actions">${action(
							"edit-book",
							"تعديل",
							row,
							true,
						)}${
							row.route
								? `<a class="owner-dashboard-record-link" href="/${escape(
										row.route,
									)}">عرض</a>`
								: ""
						}</div>`,
				},
			],
			"لا توجد كتب مطابقة.",
		);
		table(
			"members",
			data.members,
			[
				{
					label: "العضو",
					render: (row) =>
						`${recordLink(
							row,
							row.display_name,
						)}<small class="owner-dashboard-cell-note"><bdi>${escape(
							row.email || "—",
						)}</bdi></small>`,
				},
				{
					label: "الحالة",
					render: (row) =>
						badge(
							row.is_suspended ? "موقوف" : "نشط",
							row.is_suspended ? "is-amber" : "is-green",
						),
				},
				{
					label: "الاستعارات",
					render: (row) => `${row.active_rentals} / ${row.max_active_rentals || 3}`,
				},
				{ label: "المستحقات", render: (row) => money(row.balance) },
				{
					label: "الإجراء",
					render: (row) =>
						`<div class="owner-dashboard-row-actions">${action(
							"edit-member",
							"تعديل",
							row,
							true,
						)}${action(
							"suspend",
							row.is_suspended ? "تفعيل" : "إيقاف",
							row,
							true,
						)}</div>`,
				},
			],
			"لا توجد عضويات مطابقة.",
		);
		table(
			"payments",
			data.payments,
			[
				{
					label: "الاستعارة",
					render: (row) =>
						`${recordLink(
							row,
							row.name,
						)}<small class="owner-dashboard-cell-note">${escape(
							row.book_title,
						)}</small>`,
				},
				{ label: "العضو", render: (row) => escape(row.member_name) },
				{ label: "رسوم التأجير", render: (row) => money(row.rental_fee) },
				{ label: "رسوم التأخير", render: (row) => money(row.late_fee) },
				{ label: "الإجمالي", render: (row) => money(row.total_amount) },
				{
					label: "الحالة",
					render: (row) =>
						badge(
							paymentLabels[row.payment_status],
							row.payment_status === "Paid" ? "is-green" : "is-amber",
						),
				},
				{ label: "الإجراء", render: (row) => action("payment", "تسجيل الدفع", row, true) },
			],
			"لا توجد استعارات مؤكدة مطابقة.",
		);
		table(
			"history",
			data.history,
			[
				{ label: "المعاملة", render: (row) => recordLink(row, row.name) },
				{ label: "الكتاب", render: (row) => escape(row.book_title) },
				{ label: "العضو", render: (row) => escape(row.member_name) },
				{ label: "النوع", render: (row) => (row.type === "Issue" ? "استعارة" : "إرجاع") },
				{ label: "التاريخ", render: (row) => date(row.date) },
				{
					label: "الحالة",
					render: (row) =>
						`${badge(stateLabels[row.rental_state] || row.rental_state)}${
							row.rejection_reason
								? `<small class="owner-dashboard-cell-note">${escape(
										row.rejection_reason,
									)}</small>`
								: ""
						}`,
				},
			],
			"لا توجد معاملات مطابقة.",
		);
	}
	function renderCharts() {
		const revenueHost = document.getElementById("owner-revenue-chart");
		const inventoryHost = document.getElementById("owner-inventory-chart");
		revenueHost.innerHTML = "";
		inventoryHost.innerHTML = "";
		if (data.summary.billed > 0) {
			new frappe.Chart(revenueHost, {
				type: "bar",
				height: 230,
				colors: ["#a6b7a9", "#243e37"],
				data: {
					labels: data.monthly.map((row) => row.month),
					datasets: [
						{ name: "رسوم مؤكدة", values: data.monthly.map((row) => row.billed) },
						{ name: "مسجّل كمدفوع", values: data.monthly.map((row) => row.paid) },
					],
				},
				barOptions: { spaceRatio: 0.4 },
			});
		} else {
			revenueHost.innerHTML =
				'<p class="owner-dashboard-empty">لا توجد رسوم تأجير مؤكدة خلال الفترة المحددة.</p>';
		}
		const categories = [
			{ key: "Available", label: "متاح", color: "#446257" },
			{ key: "Issued", label: "مستعار", color: "#b99a71" },
			{ key: "Display", label: "للعرض فقط", color: "#a6b7a9" },
			{ key: "Unknown", label: "حالة غير محددة", color: "#d0b9a3" },
		].filter((item) => data.inventory[item.key]);
		if (categories.length) {
			new frappe.Chart(inventoryHost, {
				type: "donut",
				height: 230,
				colors: categories.map((item) => item.color),
				data: {
					labels: categories.map((item) => item.label),
					datasets: [{ values: categories.map((item) => data.inventory[item.key]) }],
				},
				showLegend: false,
			});
		} else {
			inventoryHost.innerHTML =
				'<p class="owner-dashboard-empty">أضف كتباً لبدء متابعة المخزون.</p>';
		}
		document.getElementById("owner-inventory-legend").innerHTML = categories
			.map(
				(item) =>
					`<span><i style="background:${item.color}"></i>${item.label} <strong>${
						data.inventory[item.key]
					}</strong></span>`,
			)
			.join("");
	}
	function render() {
		root.querySelectorAll("[data-metric]").forEach((node) => {
			const key = node.dataset.metric;
			node.innerHTML = ["paid", "outstanding"].includes(key)
				? money(data.summary[key])
				: String(data.summary[key]);
		});
		const notes = {
			available: `من ${data.summary.books} كتاب`,
			active: `${data.summary.issued} كتاب بحالة مستعار`,
			pending: "طلبات غير معتمدة، دون احتسابها إيراداً",
			overdue: "لم تسجّل لها معاملة إرجاع",
			paid: "حسب تاريخ اعتماد الاستعارة",
			outstanding: "جميع الاستعارات غير المدفوعة",
		};
		root.querySelectorAll("[data-metric-note]").forEach((node) => {
			node.textContent = notes[node.dataset.metricNote];
		});
		document.getElementById("owner-billed").innerHTML = money(data.summary.billed);
		document.getElementById("owner-refunded").innerHTML = money(data.summary.refunded);
		document.getElementById("owner-inventory-summary").textContent =
			`${data.summary.books} كتاب • ${data.summary.members} عضو`;
		document.getElementById("owner-alerts-panel").hidden = !data.alerts.length;
		document.getElementById("owner-alerts").innerHTML = data.alerts
			.map(
				(alert) =>
					`<li><span>${escape(alert.message)}</span><a href="${escape(
						alert.url,
					)}">مراجعة السجل &larr;</a></li>`,
			)
			.join("");
		renderTables();
		renderCharts();
		status.textContent = `بيانات محدثة • ${frappe.datetime.str_to_user(data.today)} • ${
			data.timezone || "Africa/Cairo"
		}`;
	}
	async function refresh() {
		if (refreshing) return;
		const from = fromDate.get_value();
		const to = toDate.get_value();
		if (!from || !to) {
			frappe.msgprint("يرجى تحديد تاريخ البداية والنهاية.");
			return;
		}
		refreshing = true;
		document.getElementById("owner-refresh").disabled = true;
		status.textContent = "جارٍ تحديث البيانات…";
		try {
			data = await call("get_dashboard", { from_date: from, to_date: to });
			render();
		} catch (error) {
			status.textContent =
				"تعذّر التحديث. البيانات المعروضة هي آخر نسخة محمّلة؛ جرّب التحديث مرة أخرى.";
		} finally {
			refreshing = false;
			document.getElementById("owner-refresh").disabled = false;
		}
	}
	function dialog(title, fields, method, args, label = "حفظ") {
		const form = new frappe.ui.Dialog({
			title,
			fields,
			primary_action_label: label,
			primary_action: async function (values) {
				form.get_primary_btn().prop("disabled", true);
				try {
					await call(method, args(values));
					form.hide();
					await refresh();
					frappe.show_alert({ message: "تم حفظ العملية بنجاح", indicator: "green" });
				} catch (error) {
					// Frappe displays server validation and permission errors.
				} finally {
					form.get_primary_btn().prop("disabled", false);
				}
			},
		});
		form.show();
		return form;
	}
	const rentalFields = (days = 7) => [
		{
			fieldtype: "Date",
			fieldname: "date",
			label: "تاريخ الاستعارة",
			default: data.today,
			reqd: 1,
		},
		{
			fieldtype: "Int",
			fieldname: "rental_duration_days",
			label: "مدة الاستعارة بالأيام",
			default: days,
			reqd: 1,
		},
	];
	function bookDialog(book) {
		dialog(
			book ? "تعديل الكتاب" : "إضافة كتاب",
			[
				{
					fieldtype: "Data",
					fieldname: "title",
					label: "عنوان الكتاب",
					default: book?.title,
					reqd: 1,
				},
				{ fieldtype: "Data", fieldname: "author", label: "المؤلف", default: book?.author },
				{ fieldtype: "Data", fieldname: "ispn", label: "ISBN", default: book?.ispn },
				{
					fieldtype: "Currency",
					fieldname: "rental_rate_per_day",
					label: "التأجير اليومي (EGP)",
					default: book?.rental_rate_per_day || 0,
				},
				{
					fieldtype: "Currency",
					fieldname: "security_deposit",
					label: "التأمين المسترد (EGP)",
					default: book?.security_deposit || 0,
				},
				{
					fieldtype: "Check",
					fieldname: "is_rentable",
					label: "متاح للعرض والتأجير في الكتالوج",
					default: book ? book.is_rentable : 1,
				},
				{
					fieldtype: "Attach Image",
					fieldname: "image",
					label: "غلاف الكتاب",
					default: book?.image,
					options: { make_attachments_public: true },
				},
				{
					fieldtype: "Text Editor",
					fieldname: "description",
					label: "عن الكتاب",
					default: book?.description,
				},
			],
			"save_book",
			(values) => ({ name: book?.name, values }),
		);
	}
	function memberDialog(member) {
		dialog(
			member ? "تعديل العضوية" : "إضافة عضو",
			[
				{
					fieldtype: "Data",
					fieldname: "first_name",
					label: "الاسم الأول",
					default: member?.first_name,
					reqd: 1,
				},
				{
					fieldtype: "Data",
					fieldname: "last_name",
					label: "اسم العائلة",
					default: member?.last_name,
				},
				{
					fieldtype: "Data",
					fieldname: "email",
					label: "البريد الإلكتروني",
					options: "Email",
					default: member?.email,
					reqd: 1,
					description: "للتأجير عبر الموقع، يجب أن يطابق بريد حساب دخول مفعّل.",
				},
				{ fieldtype: "Data", fieldname: "phone", label: "الهاتف", default: member?.phone },
				{
					fieldtype: "Int",
					fieldname: "max_active_rentals",
					label: "الحد الأقصى للاستعارات النشطة",
					default: member?.max_active_rentals || 3,
					reqd: 1,
				},
			],
			"save_member",
			(values) => ({ name: member?.name, values }),
		);
	}
	function handleAction(kind, name) {
		const row = name ? find(name) : null;
		if (kind === "new-book") return bookDialog();
		if (kind === "edit-book") return bookDialog(data.books.find((book) => book.name === name));
		if (kind === "new-member") return memberDialog();
		if (kind === "edit-member")
			return memberDialog(data.members.find((member) => member.name === name));
		if (kind === "new-issue") {
			const selectOptions = (placeholder, records, getLabel) => [
				{ value: "", label: placeholder },
				...records.map((record) => ({
					value: record.name,
					label: escape(getLabel(record)),
				})),
			];
			const availableBooks = data.books.filter(
				(book) => book.status === "Available" && book.is_rentable,
			);
			const activeMembers = data.members.filter((member) => !member.is_suspended);
			return dialog(
				"استعارة جديدة",
				[
					{
						fieldtype: "Select",
						fieldname: "article",
						label: "الكتاب",
						options: selectOptions("اختر الكتاب", availableBooks, (book) => book.title),
						reqd: 1,
					},
					{
						fieldtype: "Select",
						fieldname: "library_member",
						label: "العضو",
						options: selectOptions("اختر العضو", activeMembers, (member) => member.display_name),
						reqd: 1,
					},
					...rentalFields(),
				],
				"issue_book",
				(values) => values,
				"تأكيد الاستعارة",
			);
		}
		if (kind === "approve" && row)
			return dialog(
				"اعتماد طلب التأجير",
				[
					{
						fieldtype: "Data",
						fieldname: "book_title",
						label: "الكتاب",
						default: row.book_title,
						read_only: 1,
					},
					{
						fieldtype: "Data",
						fieldname: "member_name",
						label: "العضو",
						default: row.member_name,
						read_only: 1,
					},
					...rentalFields(row.rental_duration_days || 7),
				],
				"approve_request",
				(values) => ({
					name,
					date: values.date,
					rental_duration_days: values.rental_duration_days,
				}),
				"اعتماد الاستعارة",
			);
		if (kind === "reject" && row)
			return dialog(
				"رفض طلب التأجير",
				[
					{
						fieldtype: "Data",
						fieldname: "book_title",
						label: "الكتاب",
						default: row.book_title,
						read_only: 1,
					},
					{ fieldtype: "Small Text", fieldname: "reason", label: "سبب الرفض", reqd: 1 },
				],
				"reject_request",
				(values) => ({ name, reason: values.reason }),
				"تأكيد الرفض",
			);
		if (kind === "return" && row)
			return dialog(
				"تسجيل إرجاع الكتاب",
				[
					{
						fieldtype: "Data",
						fieldname: "book_title",
						label: "الكتاب",
						default: row.book_title,
						read_only: 1,
					},
					{
						fieldtype: "Date",
						fieldname: "date",
						label: "تاريخ الإرجاع",
						default: data.today,
						reqd: 1,
					},
				],
				"return_book",
				(values) => ({ name, date: values.date }),
				"تأكيد الإرجاع",
			);
		if (kind === "payment" && row)
			return dialog(
				"تسجيل حالة الدفع",
				[
					{
						fieldtype: "Data",
						fieldname: "book_title",
						label: "الكتاب",
						default: row.book_title,
						read_only: 1,
					},
					{
						fieldtype: "Currency",
						fieldname: "rental_fee",
						label: "رسوم التأجير الأصلية (EGP)",
						default: row.rental_fee,
						read_only: 1,
					},
					{
						fieldtype: "Currency",
						fieldname: "late_fee",
						label: "رسوم التأخير المقررة (EGP)",
						default: row.late_fee || 0,
						description: "تُحدّد يدوياً وفق سياسة المكتبة، دون رسوم تلقائية.",
					},
					{
						fieldtype: "Select",
						fieldname: "payment_status",
						label: "حالة الدفع",
						default: row.payment_status,
						reqd: 1,
						options: Object.entries(paymentLabels).map(([value, label]) => ({
							value,
							label,
						})),
					},
				],
				"update_payment",
				(values) => ({
					name,
					payment_status: values.payment_status,
					late_fee: values.late_fee,
				}),
			);
		if (kind === "suspend") {
			const member = data.members.find((member) => member.name === name);
			if (!member) return;
			return dialog(
				member.is_suspended ? "تفعيل العضوية" : "إيقاف العضوية",
				[
					{
						fieldtype: "Data",
						fieldname: "member",
						label: "العضو",
						default: member.display_name,
						read_only: 1,
					},
				],
				"set_member_suspended",
				() => ({ name, suspended: member.is_suspended ? 0 : 1 }),
				"تأكيد",
			);
		}
	}
	function selectTab(key, focus = false) {
		activeTab = key;
		root.querySelectorAll("[data-tab]").forEach((button) => {
			const selected = button.dataset.tab === key;
			button.classList.toggle("is-active", selected);
			button.setAttribute("aria-selected", String(selected));
			button.tabIndex = selected ? 0 : -1;
			if (selected && focus) button.focus();
			document.getElementById("owner-panel-" + button.dataset.tab).hidden = !selected;
		});
		bookStatus.$wrapper.toggle(key === "books");
	}
	root.addEventListener("click", function (event) {
		const tab = event.target.closest("[data-tab]");
		if (tab) {
			selectTab(tab.dataset.tab);
			return;
		}
		const button = event.target.closest("button[data-action]");
		if (button) handleAction(button.dataset.action, button.dataset.name);
	});
	root.querySelector("[role=tablist]").addEventListener("keydown", function (event) {
		const tabs = Array.from(root.querySelectorAll("[data-tab]"));
		const current = tabs.findIndex((tab) => tab.dataset.tab === activeTab);
		let next;
		if (event.key === "ArrowLeft") next = (current + 1) % tabs.length;
		if (event.key === "ArrowRight") next = (current + tabs.length - 1) % tabs.length;
		if (event.key === "Home") next = 0;
		if (event.key === "End") next = tabs.length - 1;
		if (next !== undefined) {
			event.preventDefault();
			selectTab(tabs[next].dataset.tab, true);
		}
	});
	search.$input.on("input", renderTables);
	bookStatus.$input.on("change", renderTables);
	document.getElementById("owner-refresh").addEventListener("click", refresh);
	selectTab("requests");
	render();
});
