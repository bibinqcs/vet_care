import frappe
import json
from frappe import _
from frappe.utils import today, getdate
from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account
from toolz import pluck, partial, compose, first, concat


@frappe.whitelist()
def get_pet_relations(pet):
    return compose(list, partial(pluck, 'customer'))(
        frappe.get_all(
            'Pet Relation',
            filters={'parent': pet},
            fields=['customer']
        )
    )


@frappe.whitelist()
def apply_core_overrides():
    frappe.db.sql("""
        UPDATE `tabDocField` 
        SET set_only_once = 0
        WHERE parent = 'Patient'
        AND fieldname = 'customer'
    """)
    frappe.db.sql("""
        UPDATE `tabDocType`
        SET autoname = 'VS-.#####'
        WHERE name = 'Vital Signs'
    """)
    frappe.db.commit()

    return True


@frappe.whitelist()
def make_invoice(dt, dn):
    sales_invoice = frappe.new_doc('Sales Invoice')

    template = frappe.get_value('Lab Test', dn, 'template')
    rate = frappe.get_value('Lab Test Template', template, 'lab_test_rate')

    sales_invoice.append('items', {
        'item_code': template,
        'qty': 1,
        'rate': rate,
        'reference_dt': dt,
        'reference_dn': dn
    })

    patient = frappe.get_value('Lab Test', dn, 'patient')
    customer = frappe.get_value('Patient', patient, 'customer')
    sales_invoice.update({
        'patient': patient,
        'customer': customer,
        'due_date': today()
    })

    sales_invoice.set_missing_values()

    return sales_invoice


@frappe.whitelist()
def make_invoice_for_encounter(dt, dn):
    sales_invoice = frappe.new_doc('Sales Invoice')

    practitioner = frappe.get_value('Patient Encounter', dn, 'practitioner')
    op_consulting_charge_item = frappe.get_value('Healthcare Practitioner', practitioner, 'op_consulting_charge_item')
    op_consulting_charge = frappe.db.get_value('Healthcare Practitioner', practitioner, 'op_consulting_charge')

    sales_invoice.append('items', {
        'item_code': op_consulting_charge_item,
        'qty': 1,
        'rate': op_consulting_charge,
        'reference_dt': dt,
        'reference_dn': dn
    })

    patient = frappe.get_value('Patient Encounter', dn, 'patient')
    customer = frappe.get_value('Patient', patient, 'customer')

    sales_invoice.update({
        'patient': patient,
        'customer': customer,
        'due_date': today()
    })

    sales_invoice.set_missing_values()

    return sales_invoice


# deprecated
@frappe.whitelist()
def get_medical_records(patient):
    return frappe.get_all(
        'Patient Medical Record',
        filters={'patient': patient},
        fields=['reference_doctype', 'reference_name', 'communication_date']
    )


@frappe.whitelist()
def save_invoice(items, patient, customer):
    items = json.loads(items)

    pos_profile = frappe.db.get_single_value('Vetcare Settings', 'pos_profile')

    if not pos_profile:
        frappe.throw(_('Please set POS Profile under Vetcare Settings'))

    sales_invoice = frappe.new_doc('Sales Invoice')
    sales_invoice.update({
        'patient': patient,
        'customer': customer,
        'due_date': today(),
        'pos_profile': pos_profile
    })

    for item in items:
        sales_invoice.append('items', {
            'item_code': item.get('item_code'),
            'qty': item.get('qty'),
            'rate': item.get('rate')
        })

    sales_invoice.set_missing_values()
    sales_invoice.save()

    return sales_invoice


@frappe.whitelist()
def pay_invoice(invoice, payments):
    def get_mode_of_payment(company, mop):
        data = get_bank_cash_account(mop.get('mode_of_payment'), company)
        return {
            'mode_of_payment': mop.get('mode_of_payment'),
            'amount': mop.get('amount'),
            'account': data.get('account'),
        }

    payments = json.loads(payments)

    invoice = frappe.get_doc('Sales Invoice', invoice)
    invoice.update({'is_pos': 1})

    get_mop_data = partial(get_mode_of_payment, invoice.company)
    payments = list(map(get_mop_data, payments))
    for payment in payments:
        invoice.append('payments', payment)

    invoice.save()
    invoice.submit()

    return invoice


# TODO: clinical history include only submitted Sales Invoice
@frappe.whitelist()
def get_clinical_history(patient, filter_length):
    """
    Patient's Clinical History is consist of:
    (1) Patient Activity
    (2) Sales Invoice Items

    Clinical History returns structurally:
    ('posting_date', 'description', 'price')
    """
    filter_length = int(filter_length)

    clinical_history_items = frappe.db.sql("""
        (SELECT 
            si.posting_date,
            CONCAT(
                ROUND(si_item.qty, 2),
                ' x ',
                si_item.item_code
            ) AS description,
            ROUND(si_item.amount, 3) AS price,
            si_item.creation
        FROM `tabSales Invoice Item` si_item
        INNER JOIN `tabSales Invoice` si ON si.name = si_item.parent
        WHERE si.customer = %s AND si.docstatus = 1)
        UNION ALL
        (SELECT
            pa.posting_date,
            CONCAT(
                UPPER(pa_item.activity_type),
                ': ',
                pa_item.description
            ) AS description,
            '' AS price,
            pa_item.creation
        FROM `tabPatient Activity Item` pa_item
        INNER JOIN `tabPatient Activity` pa on pa.name = pa_item.parent
        WHERE pa.patient = %s)
        ORDER BY creation DESC
        LIMIT %s
    """, (frappe.get_value('Patient', patient, 'customer'), patient, filter_length), as_dict=True)

    return clinical_history_items


@frappe.whitelist()
def make_patient_activity(patient, activity_items):
    activity_items = json.loads(activity_items)

    patient_activity = frappe.get_doc({
        'doctype': 'Patient Activity',
        'patient': patient,
        'posting_date': today()
    })

    for activity_item in activity_items:
        patient_activity.append('items', {
            'activity_type': activity_item['activity_type'],
            'description': activity_item['description']
        })

    patient_activity.save()

    return patient_activity


@frappe.whitelist()
def get_invoice_items(invoice):
    return frappe.get_all(
        'Sales Invoice Item',
        filters={'parent': invoice},
        fields=['item_code', 'qty', 'rate', 'amount']
    )


@frappe.whitelist()
def save_to_patient(patient, data):
    data = json.loads(data)
    patient_doc = frappe.get_doc('Patient', patient)
    patient_doc.update(data)
    patient_doc.save()


@frappe.whitelist()
def make_patient(patient_data, owner):
    patient_data = json.loads(patient_data)

    patient_doc = frappe.new_doc('Patient')
    patient_doc.update(patient_data)
    patient_doc.append('vc_pet_relation', {
        'default': 1,
        'relation': 'Owner',
        'customer': owner
    })
    patient_doc.save()

    return patient_doc


@frappe.whitelist()
def get_first_animal_by_owner(owner):
    data = frappe.get_all('Patient', filters={'customer': owner})
    return first(data) if data else None


@frappe.whitelist()
# TODO: filter availables
def get_practitioner_schedules(practitioner, date):
    def schedule_times(week_date, practitioner_schedule):
        return _get_schedule_times(practitioner_schedule, week_date)

    data = compose(
        set,
        sorted,
        concat,
        partial(map, partial(schedule_times, getdate(date)))
    )

    practitioner_schedules = data(
        frappe.get_all(
            'Practitioner Service Unit Schedule',
            filters={'parent': practitioner},
            fields=['schedule']
        )
    )

    data_bookings = compose(
        set,
        partial(map, lambda x: x.get('appointment_time'))
    )

    existing_bookings = data_bookings(
        frappe.get_all(
            'Patient Booking',
            filters={
                'physician': practitioner,
                'appointment_date': date,
                'docstatus': 1
            },
            fields=['appointment_time']
        )
    )

    return compose(list, partial(map, str), sorted)(practitioner_schedules.difference(existing_bookings))


def _get_schedule_times(name, date):
    """
    Fetch all `from_time` from [Healthcare Schedule Time Slot]
    :param name: [Practitioner Schedule]
    :param date: [datetime.date]
    :return:
    """
    mapped_day = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    time_slots = frappe.get_all(
        'Healthcare Schedule Time Slot',
        filters={'parent': name, 'day': mapped_day[date.weekday()]},
        fields=['from_time']
    )
    return list(map(lambda x: x.get('from_time'), time_slots))


# TODO: include also with Patient
def _get_sales_invoice_items(customer):
    return frappe.db.sql("""
        SELECT 
            si.posting_date,
            si_item.item_code,
            si_item.qty,
            si_item.amount
        FROM `tabSales Invoice Item` si_item
        INNER JOIN `tabSales Invoice` si ON si.name = si_item.parent
        WHERE si.customer = %s
    """, (customer,), as_dict=1)
