// Copyright (c) 2020, 9T9IT and contributors
// For license information, please see license.txt
{% include 'vet_care/vet_care/doctype/animal_overview/payment_dialog.js' %}
{% include 'vet_care/vet_care/doctype/animal_overview/custom_buttons.js' %}

let _filter_length = 20;

frappe.ui.form.on('Animal Overview', {
	onload: function(frm) {
		frm.set_query('default_owner', function() {
			return {
				query: "erpnext.controllers.queries.customer_query",
			};
		});
	},
	refresh: function(frm) {
		frm.disable_save();
		set_custom_buttons(frm);
		_set_actions(frm);
		_set_fields_read_only(frm, true);
	},
	animal: function(frm) {
		_set_animal_details(frm);
		_set_clinical_history(frm);
		_set_invoice_query(frm);
		_set_fields_read_only(frm, !frm.doc.animal);
	},
	invoice: async function(frm) {
		if (frm.doc.invoice) {
			const items = await _get_invoice_items(frm.doc.invoice);
			frm.set_value('items', items);
			frm.set_df_property('items', 'read_only', true);
		}
	},
  default_owner: function(frm) {
	  _set_default_owner_query(frm);
  },
	new_activity: async function(frm) {
		if (!frm.doc.animal) {
			frappe.throw(__('Animal is required.'));
			return;
		}

		const { message: patient_activity } = await frappe.call({
			method: 'vet_care.api.make_patient_activity',
			args: {
				patient: frm.doc.animal,
				activity_type: frm.doc.activity_type,
				description: frm.doc.description
			}
		});
		frappe.show_alert(`Patient Activity created`);

		// clear data
		frm.set_value('activity_type', '');
		frm.set_value('description', '');

		// refresh clinical history
		_set_clinical_history(frm);
	}
});

frappe.ui.form.on('Animal Overview Item', {
	qty: function(frm, cdt, cdn) {
		_update_child_amount(frm, cdt, cdn);
	},
	rate: function(frm, cdt, cdn) {
		_update_child_amount(frm, cdt, cdn);
	},
	item_code: async function(frm, cdt, cdn) {
		const child = _get_child(cdt, cdn);

		if (!child.qty) {
			frappe.model.set_value(cdt, cdn, 'qty', 1.0);
		}

		if (!child.rate) {
			const { message: item } = await frappe.db.get_value(
				'Item',
				{ name: child.item_code },
				'standard_rate',
			);
			frappe.model.set_value(cdt, cdn, 'rate', item.standard_rate);
		}
	},
});

function _set_fields_read_only(frm, read_only) {
	const fields = [
		'animal_name',
		'dob',
		'weight',
		'sex',
		'breed',
		'species',
		'color',
		'activity_type',
		'description',
		'invoice',
		'items'
	];
	fields.forEach((field) => frm.set_df_property(field, 'read_only', read_only));
}

function _set_invoice_query(frm) {
	frm.set_query('invoice', function(doc, cdt, cdn) {
		return {
			filters: {
				'status': 'Draft',
				'patient': frm.doc.animal,
			}
		};
	});
}

function _set_default_owner_query(frm) {
  frm.set_query('animal', function(doc, cdt, cdn) {
    return {
      filters: { 'customer': frm.doc.default_owner }
    }
  });
}

async function _set_animal_details(frm) {
	const patient = await frappe.db.get_doc('Patient', frm.doc.animal);
	frm.set_value('animal_name', patient.patient_name);
	frm.set_value('species', patient.vc_species);
	frm.set_value('color', patient.vc_color);
	frm.set_value('sex', patient.sex);
	frm.set_value('dob', patient.dob);
	frm.set_value('weight', patient.vc_weight);
	frm.set_value('default_owner', patient.customer);
	frm.set_value('breed', patient.vc_breed);
}

async function _set_clinical_history(frm) {
	const { message: clinical_history } = await frappe.call({
		method: 'vet_care.api.get_clinical_history',
		args: {
			patient: frm.doc.animal,
			filter_length: _filter_length,
		},
	});

	const fields = ['posting_date', 'description', 'price'];

	const table_rows = _get_table_rows(clinical_history, fields);
	const table_header = _get_table_header(fields);

	// TODO: separate to renderer
	$(frm.fields_dict['clinical_history_html'].wrapper).html(`
		<table class="table table-bordered">
			${table_header}
			${table_rows.join('\n')}
		</table>
		<div class="list-paging-area level">
			<div class="btn-group">
				<button class="btn btn-default btn-paging" data-value="20">20</button>
				<button class="btn btn-default btn-paging" data-value="100">100</button>
				<button class="btn btn-default btn-paging" data-value="500">500</button>
			</div>
			<div>
				<button class="btn btn-default btn-more">More...</button>
			</div>
		</div>
	`);

	_set_clinical_history_buttons(frm);
}

function _set_clinical_history_buttons(frm) {
	$('.btn-paging').click(function() {
		_filter_length = $(this).data('value');
		_set_clinical_history(frm);
	});
}

function _set_actions(frm) {
	$(frm.fields_dict['actions_html'].wrapper).html(`
		<div class="row">
			<div class="col-sm-6">
				<button class="btn btn-xs btn-info" id="save">Save</button>
				<button class="btn btn-xs btn-primary" id="close">Close</button>
				<button class="btn btn-xs btn-danger" id="discard">Discard</button>
			</div>
		</div>
	`);

	const actions = {
		save: async function() {
			if (!frm.doc.items.length) {
				frappe.throw(__('Items are required'));
			}

			await _close_invoice(
				frm.doc.items,
				frm.doc.animal,
				frm.doc.default_owner,
				[],
				false
			);

			frm.set_value('items', []);
		},
		close: async function() {
			if (!frm.doc.invoice) {
				frappe.throw(__('Please select invoice above'));
			}

			const values = await show_payment_dialog(frm);
			_pay_invoice(frm.doc.invoice, values.payments);

			frm.set_value('invoice', '');
			frm.set_value('items', []);

			// reload clinical history
			_set_clinical_history(frm);
		},
		discard: function() {
			frm.set_value('invoice', '');
			frm.set_value('items', []);
		}
	};

	_map_buttons_to_functions(actions, {
		decorator_fn: (fn) => {
			if (!frm.doc.animal) {
				frappe.throw(__('Animal is required.'));
				return;
			}
			fn();
		},
	});
}

function _update_child_amount(frm, cdt, cdn) {
	const child = _get_child(cdt, cdn);
	frappe.model.set_value(cdt, cdn, 'amount', child.qty * child.rate);
}

// TODO: rewrite with no payments and submit
async function _close_invoice(items, patient, customer, payments, submit) {
	const { message: invoice } = await frappe.call({
		method: 'vet_care.api.close_invoice',
		args: {
			items,
			patient,
			customer,
			payments,
			submit,
		},
	});
	frappe.show_alert(`Sales Invoice ${invoice.name} created`);
}

async function _pay_invoice(invoice, payments) {
	const { message: sales_invoice } = await frappe.call({
		method: 'vet_care.api.pay_invoice',
		args: { invoice, payments },
	});
	frappe.show_alert(`Sales Invoice ${sales_invoice.name} is paid`);
}

async function _get_invoice_items(invoice) {
	const { message: items } = await frappe.call({
		method: 'vet_care.api.get_invoice_items',
		args: { invoice },
	});
	return items;
}

// table utils
function _get_table_rows(records, fields) {
	return records.map((record) => {
		if (!fields)
			fields = Object.keys(record);
		const table_data = fields.map((field) =>
			`<td>${record[field]}</td>`);
		return `<tr>${table_data.join('\n')}</tr>`;
	});
}

function _get_table_header(fields) {
	const header_texts = fields.map((field) =>
		field.split('_')
			.map((s) => s.charAt(0).toUpperCase() + s.substring(1))
			.join(' ')
	);
	const columns = header_texts.map((column) =>
		`<th>${column}</th>`);
	return `<tr>${columns.join('\n')}</tr>`;
}

// actions utils
function _map_buttons_to_functions(actions, args) {
	const decorator_fn = args.decorator_fn
		? args.decorator_fn
		: null;
	Object.keys(actions).forEach((action) => {
		$(`#${action}`).click(
			decorator_fn
				? () => decorator_fn(actions[action])
				: actions[action]
		);
	});
}

// child table utils
function _get_child(cdt, cdn) {
	return locals[cdt][cdn];
}
