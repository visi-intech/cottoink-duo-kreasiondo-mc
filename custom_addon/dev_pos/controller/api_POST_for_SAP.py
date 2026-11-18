from odoo import http, api, SUPERUSER_ID
from concurrent.futures import ThreadPoolExecutor, as_completed
from odoo.http import request
import requests
from datetime import datetime
import json
import logging
import base64
from odoo.exceptions import AccessError
from ..models.merchandise_category import MERCHANDISE_CATEGORY_FIELDS, MERCHANDISE_CATEGORY_LEGACY_KEYS

_logger = logging.getLogger(__name__)


# ==================== CUSTOMER GROUP API ====================

def is_customer_group_pricelist_enabled():
    """Check if vit_cust_group_pricelist is enabled"""
    config = request.env['ir.config_parameter'].sudo()
    return config.get_param('pos.vit_cust_group_pricelist') == 'True'

def is_customer_group_pricelist_enabled():
    config = request.env['ir.config_parameter'].sudo()
    return config.get_param('pos.vit_cust_group_pricelist') == 'True'


class POSTCustomerGroup(http.Controller):

    @http.route('/api/master_customer_group', type='json', auth='none', methods=['POST'], csrf=False)
    def post_customer_group(self, **kw):
        try:
            # 🔐 Cek fitur aktif
            if not is_customer_group_pricelist_enabled():
                return {
                    'status': 'Failed',
                    'code': 403,
                    'message': 'Customer Group Pricelist feature is not enabled. Enable in POS Settings.'
                }

            # 🔐 Authentication
            config = request.env['setting.config'].sudo().search(
                [('vit_config_server', '=', 'mc')], limit=1
            )
            if not config:
                return {'status': 'Failed', 'code': 500, 'message': "Configuration not found."}

            uid = request.session.authenticate(
                request.session.db,
                config.vit_config_username,
                config.vit_config_password_api
            )
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)

            # JSON Input
            data = request.get_json_data()
            items = data.get('items', [])

            # Normalize input → harus list
            if isinstance(items, dict):
                items = [items]
            elif not isinstance(items, list):
                return {
                    'status': 'Failed',
                    'code': 400,
                    'message': "'items' must be a list or object."
                }

            created = []
            failed = []

            # 🚀 Process each group
            for row in items:
                try:
                    name = row.get('group_name')
                    pricelist_id = row.get('pricelist_id')

                    if not name:
                        failed.append({'data': row, 'message': "Missing group_name", 'id': None})
                        continue

                    if not pricelist_id:
                        failed.append({'data': row, 'message': "Missing pricelist_id", 'id': None})
                        continue

                    # Cek duplikat
                    existing = env['customer.group'].sudo().search(
                        [('vit_group_name', '=', name)], limit=1
                    )
                    if existing:
                        failed.append({
                            'data': row,
                            'message': f"Duplicate customer group '{name}'",
                            'id': existing.id
                        })
                        continue

                    # Validasi pricelist
                    pricelist = env['product.pricelist'].sudo().browse(pricelist_id)
                    if not pricelist.exists():
                        failed.append({
                            'data': row,
                            'message': f"Pricelist ID {pricelist_id} not found",
                            'id': None
                        })
                        continue

                    # Create
                    vals = {
                        'vit_group_name': name,
                        'vit_pricelist_id': pricelist_id,
                        'create_uid': uid,
                    }

                    group = env['customer.group'].sudo().create(vals)

                    created.append({
                        'id': group.id,
                        'group_name': group.vit_group_name,
                        'pricelist_id': group.vit_pricelist_id.id,
                        'pricelist_name': group.vit_pricelist_id.name,
                    })

                except Exception as e:
                    failed.append({
                        'data': row,
                        'message': f"Error: {str(e)}",
                        'id': None
                    })

            return {
                'code': 200 if not failed else 207,
                'status': 'success' if not failed else 'partial_success',
                'created_groups': created,
                'failed_groups': failed
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create customer groups: {str(e)}", exc_info=True)
            return {
                'status': 'Failed',
                'code': 500,
                'message': f"Failed to create customer groups: {str(e)}"
            }
        
class PATCHCustomerGroup(http.Controller):

    @http.route('/api/master_customer_group', type='json', auth='none', methods=['PATCH'], csrf=False)
    def update_customer_group(self, **kwargs):
        try:
            # 🔐 Cek fitur aktif
            if not is_customer_group_pricelist_enabled():
                return {
                    'status': 'Failed',
                    'code': 403,
                    'message': 'Customer Group Pricelist feature is not enabled. Enable in POS Settings.'
                }

            # 🔐 Authentication
            config = request.env['setting.config'].sudo().search(
                [('vit_config_server', '=', 'mc')], limit=1
            )
            if not config:
                return {'status': 'Failed', 'code': 500, 'message': "Configuration not found."}

            uid = request.session.authenticate(
                request.session.db,
                config.vit_config_username,
                config.vit_config_password_api
            )
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)

            # JSON Input
            data = request.get_json_data()
            items = data.get('items', [])

            # Normalize → harus list
            if isinstance(items, dict):
                items = [items]
            elif not isinstance(items, list):
                return {
                    'status': 'Failed',
                    'code': 400,
                    'message': "'items' must be a list or object."
                }

            updated = []
            failed = []

            # 🚀 Process each update
            for row in items:
                try:
                    group_id = row.get('id')
                    if not group_id:
                        failed.append({'id': None, 'message': "Missing customer group ID"})
                        continue

                    group = env['customer.group'].sudo().browse(group_id)
                    if not group.exists():
                        failed.append({'id': group_id, 'message': "Customer group not found"})
                        continue

                    vals = {}

                    # Update name
                    if 'group_name' in row:
                        vals['vit_group_name'] = row['group_name']

                    # Update pricelist
                    if 'pricelist_id' in row:
                        pricelist = env['product.pricelist'].sudo().browse(row['pricelist_id'])
                        if not pricelist.exists():
                            failed.append({
                                'id': group_id,
                                'message': f"Pricelist ID {row['pricelist_id']} not found"
                            })
                            continue
                        vals['vit_pricelist_id'] = row['pricelist_id']

                    vals['write_uid'] = uid

                    # Clean None
                    vals = {k: v for k, v in vals.items() if v is not None}

                    group.sudo().write(vals)

                    updated.append({
                        'id': group.id,
                        'group_name': group.vit_group_name,
                        'pricelist_id': group.vit_pricelist_id.id,
                        'pricelist_name': group.vit_pricelist_id.name,
                    })

                except Exception as e:
                    failed.append({
                        'id': row.get('id'),
                        'message': f"Error: {str(e)}"
                    })

            return {
                'code': 200 if not failed else 207,
                'status': 'success' if not failed else 'partial_success',
                'updated_groups': updated,
                'failed_groups': failed
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Error updating customer group: {str(e)}", exc_info=True)
            return {
                'code': 500,
                'status': 'Failed',
                'message': f"Error updating customer groups: {str(e)}"
            }

class POSTMasterTax(http.Controller):

    @http.route('/api/master_tax', type='json', auth='none', methods=['POST'], csrf=False)
    def post_master_tax(self, **kw):
        try:
            # 🔐 Authentication
            config = request.env['setting.config'].sudo().search(
                [('vit_config_server', '=', 'mc')], limit=1
            )
            if not config:
                return {
                    'status': "Failed",
                    'code': 500,
                    'message': "Configuration not found."
                }

            uid = request.session.authenticate(
                request.session.db,
                config.vit_config_username,
                config.vit_config_password_api
            )
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            # Use admin user to avoid access issues
            env = request.env(user=request.env.ref('base.user_admin').id)

            data = request.get_json_data()
            items = data.get('items', [])

            if not isinstance(items, list):
                return {'status': "Failed", 'code': 400, 'message': "'items' must be a list."}

            created = []
            failed = []

            # 🧾 Process each tax item
            for tax_data in items:
                try:
                    name = tax_data.get('name')

                    # Cek duplicate by name
                    existing_tax = env['account.tax'].sudo().search(
                        [('name', '=', name)], limit=1
                    )

                    if existing_tax:
                        failed.append({
                            'data': tax_data,
                            'message': f"Tax '{name}' already exists.",
                            'id': existing_tax.id
                        })
                        continue

                    # Build tax fields
                    vals = {
                        'name': name,
                        'description': tax_data.get('description'),
                        'amount_type': 'percent',
                        'active': tax_data.get('active', True),
                        'amount': tax_data.get('amount', 0),
                        'invoice_label': tax_data.get('invoice_label'),
                    }

                    tax = env['account.tax'].sudo().create(vals)

                    created.append({
                        'id': tax.id,
                        'name': tax.name,
                        'amount': tax.amount,
                        'active': tax.active,
                    })

                except Exception as e:
                    failed.append({
                        'data': tax_data,
                        'message': f"Error: {str(e)}",
                        'id': None
                    })

            return {
                'code': 200,
                'status': 'success',
                'created_taxes': created,
                'failed_taxes': failed
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create taxes: {str(e)}", exc_info=True)
            return {
                'status': "Failed",
                'code': 500,
                'message': f"Failed to create taxes: {str(e)}"
            }

class POSTEmployee(http.Controller):
    @http.route('/api/hr_employee', type='json', auth='none', methods=['POST'], csrf=False)
    def post_employee(self, **kw):
        try:
            # Authentication
            config = request.env['setting.config'].sudo().search([('vit_config_server', '=', 'mc')], limit=1)
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}
            
            uid = request.session.authenticate(request.session.db, config.vit_config_username, config.vit_config_password_api)
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)
            
            data = request.get_json_data()

            # Validate 'items' must be a list
            items = data.get('items', [])
            if not isinstance(items, list):
                return {'status': "Failed", 'code': 400, 'message': "'items' must be a list."}

            created = []  # To store successfully created employees
            failed = []   # To store failed employees

            # Process each item
            for data in items:
                try:
                    # Validate department
                    department_id = data.get('department_id')
                    department = env['hr.department'].sudo().browse(department_id)

                    # Check if employee name already exists
                    existing_employee = env['hr.employee'].sudo().search([('name', '=', data.get('name'))], limit=1)
                    if existing_employee:
                        failed.append({
                            'data': data,
                            'message': f"Employee with name '{data.get('name')}' already exists.",
                            'id': existing_employee.id  # Provide the existing employee's ID
                        })
                        continue

                    # Create employee
                    employee_data = {
                        'vit_employee_code': data.get('employee_code'),
                        'name': data.get('name'),
                        'work_email': data.get('work_email'),
                        'work_phone': data.get('work_phone'),
                        'mobile_phone': data.get('mobile_phone'),
                        'create_uid': uid,
                        'private_street': data.get('address_home_id'),
                        'gender': data.get('gender'),
                        'birthday': data.get('birthdate'),
                        'is_sales': data.get('is_sales', False)
                    }

                    employee = env['hr.employee'].sudo().create(employee_data)

                    created.append({
                        'id': employee.id,
                        'employee_code': employee.vit_employee_code,
                        'name': employee.name,
                    })

                except Exception as e:
                    failed.append({
                        'data': data,
                        'message': f"Error: {str(e)}",
                        'id': None  # ID is not created, so set it to None
                    })

            # Return response
            return {
                'code': 200,
                'status': 'success',
                'created_employees': created,  # List of successfully created employees
                'failed_employees': failed    # List of employees that failed to create with ID and reason
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create employees: {str(e)}", exc_info=True)
            return {
                'status': "Failed", 
                'code': 500, 
                'message': f"Failed to create employees: {str(e)}"
            }


class POSTMasterBoM(http.Controller):
    @http.route('/api/master_bom', type='json', auth='none', methods=['POST'], csrf=False)
    def post_master_bom(self, **kw):
        try:
            # Authentication
            config = request.env['setting.config'].sudo().search([('vit_config_server', '=', 'mc')], limit=1)
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}
            
            uid = request.session.authenticate(request.session.db, config.vit_config_username, config.vit_config_password_api)
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)
            
            data = request.get_json_data()
            product_tmpl_id = data.get('product_tmpl_id')
            product_id = data.get('product_id')
            quantity = data.get('quantity')
            reference = data.get('reference')
            type = data.get('type')
            move_lines = data.get('move_lines', [])

            # Validate picking type
            product_tmpl = env['product.template'].sudo().search([('default_code', '=', product_tmpl_id)], limit=1)
            if not product_tmpl:
                return {
                    'status': "Failed", 
                    'code': 400, 
                    'message': f"Product Template '{product_tmpl.name}' not found."
                }
            
            product_variant = env['product.product'].sudo().search([('default_code', '=', product_id)], limit=1)
            if not product_variant:
                return {
                    'status': "Failed", 
                    'code': 400, 
                    'message': f"Product Variant '{product_variant.name}' not found."
                }

            # Validate all products first before creating Goods Receipt
            missing_products = []
            for line in move_lines:
                product_code = line.get('product_code')
                product_id = env['product.product'].sudo().search([('default_code', '=', product_code)], limit=1)
                if not product_id:
                    missing_products.append(product_code)

            if missing_products:
                return {
                    'status': "Failed",
                    'code': 400,
                    'message': f"Products with codes {', '.join(missing_products)} not found. Goods Receipt creation cancelled."
                }

            # Create BoM
            bom_master = env['mrp.bom'].sudo().create({
                'product_tmpl_id': product_tmpl.id,
                'product_id': product_variant.id,
                'product_qty': quantity,
                'code': reference,
                'type': type,
            })

            # Update goods receipt with move lines
            bom_master.write({
                'bom_line_ids': [(0, 0, line) for line in move_lines]
            })

            return {
                'code': 200,
                'status': 'success',
                'message': 'BoM created and validated successfully',
                'id': bom_master.id,
                'doc_num': bom_master.product_id.name
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create BoM: {str(e)}", exc_info=True)
            return {
                'status': "Failed", 
                'code': 500, 
                'message': f"Failed to create BoM: {str(e)}"
            }

# controllers/master_item.py
import logging
import time

import psycopg2
import psycopg2.errors
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# =========================================================
# KONFIGURASI BATCH
# =========================================================
LOOKUP_CHUNK            = 5000   # chunk query preload (default_code & data master)
BATCH_CREATE_SIZE       = 500    # jumlah produk per batch ORM create
COMMIT_MAX_RETRIES      = 3      # retry commit kalau kena serialization failure
COMMIT_RETRY_BASE_SLEEP = 0.2    # detik; backoff = base * attempt

# Context create massal: tidak membuat tracking value / log chatter
# "Product created" / auto-follow untuk tiap produk (sangat mahal di volume besar).
BULK_CREATE_CONTEXT = {
    'tracking_disable':         True,
    'mail_create_nolog':        True,
    'mail_create_nosubscribe':  True,
    'mail_notrack':             True,
}


# =========================================================
# HELPER
# =========================================================
def _chunks(values, size):
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _as_list(value):
    """None / '' / False -> []; nilai tunggal -> [nilai]; list -> list."""
    if value is None or value is False or value == '':
        return []
    return value if isinstance(value, list) else [value]


def _bulk_read(model, field, values, fields):
    """search_read dengan operator 'in' per chunk -> list of dict."""
    rows = []
    for chunk in _chunks(values, LOOKUP_CHUNK):
        rows.extend(model.search_read([(field, 'in', chunk)], fields))
    return rows


def _payload_val(data, field):
    """Ambil nilai payload dengan nama field (vit_artikel_code) atau key lama SAP (U_VARC / u_varc)."""
    keys = [field]
    legacy = MERCHANDISE_CATEGORY_LEGACY_KEYS.get(field)
    if legacy:
        keys += [legacy, legacy.lower()]
    for key in keys:
        if key in data:
            return key, data[key]
    return None, None


def _advisory_lock(cr, key):
    """Transaction-level advisory lock (hash dari key), otomatis lepas saat
    commit/rollback. Mengurangi konflik kalau beberapa request paralel
    menyentuh product_code yang sama."""
    cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))


def _commit_with_retry(cr, max_retries=COMMIT_MAX_RETRIES, context=""):
    """Commit dengan retry kalau kena serialization failure (SQLSTATE 40001)."""
    for attempt in range(1, max_retries + 1):
        try:
            cr.commit()
            return
        except psycopg2.errors.SerializationFailure as e:
            cr.rollback()
            _logger.warning(
                f"[{context}] Serialization failure on commit "
                f"(attempt {attempt}/{max_retries}): {e}"
            )
            if attempt == max_retries:
                _logger.error(f"[{context}] Commit gagal setelah {max_retries} retry, menyerah.")
                raise
            time.sleep(COMMIT_RETRY_BASE_SLEEP * attempt)


class POSTMasterItem(http.Controller):

    @http.route('/api/master_item', type='json', auth='none', methods=['POST'], csrf=False)
    def post_master_item(self, **kw):
        try:
            # 🔐 Autentikasi (TETAP seperti versi lama)
            config = request.env['setting.config'].sudo().search(
                [('vit_config_server', '=', 'mc')], limit=1
            )
            if not config:
                return {'code': 500, 'status': 'Failed', 'message': 'Configuration not found.'}

            uid = request.session.authenticate(
                request.session.db,
                config.vit_config_username,
                config.vit_config_password_api
            )
            if not uid:
                return {'code': 401, 'status': 'Failed', 'message': 'Authentication failed.'}

            env = request.env
            cr = request.env.cr

            Product  = env['product.template'].sudo().with_context(**BULK_CREATE_CONTEXT)
            Category = env['product.category'].sudo()
            Uom      = env['uom.uom'].sudo()
            PosCateg = env['pos.category'].sudo()
            Tax      = env['account.tax'].sudo()
            Merch    = env['vit.merchandise.category'].sudo()

            json_data = request.get_json_data()
            items = json_data.get('items', [])
            if isinstance(items, dict):
                items = [items]
            if not items:
                return {'code': 400, 'status': 'Failed', 'message': 'No items provided.'}

            # ============================================================
            # 1. KUMPULKAN KEY UNIK dari seluruh payload
            # ============================================================
            all_codes, all_categ_names, all_uom_names = set(), set(), set()
            all_pos_ids, all_tax_names = set(), set()
            all_merch_codes = set()

            for data in items:
                if data.get('product_code'):
                    all_codes.add(data['product_code'])
                if data.get('category_name'):
                    all_categ_names.add(data['category_name'])
                for key in ('uom_name', 'uom_po_name'):
                    if data.get(key):
                        all_uom_names.add(data[key])
                all_pos_ids.update(_as_list(data.get('pos_categ_ids', data.get('pos_categ_id', []))))
                all_tax_names.update(_as_list(data.get('taxes_names', [])))
                merch_code = _payload_val(data, 'vit_artikel_code')[1]
                if merch_code:
                    all_merch_codes.add(merch_code)

            # ============================================================
            # 2. PRELOAD SEMUA LOOKUP SEKALIGUS (chunked, tanpa query di dalam loop)
            # ============================================================
            # Produk yang sudah ada -- TERMASUK yang diarsipkan (active=False),
            # supaya produk arsip di-UPDATE (dan bisa diaktifkan lagi), bukan dibuat dobel.
            existing_ids, existing_active = {}, {}
            for row in _bulk_read(Product.with_context(active_test=False),
                                  'default_code', all_codes, ['default_code', 'active']):
                if row['default_code'] not in existing_ids:
                    existing_ids[row['default_code']] = row['id']
                    existing_active[row['id']] = row['active']

            categ_map = {}
            for row in _bulk_read(Category, 'complete_name', all_categ_names, ['complete_name']):
                categ_map.setdefault(row['complete_name'], row['id'])

            uom_map = {}   # name -> (id, category_id)
            for row in _bulk_read(Uom, 'name', all_uom_names, ['name', 'category_id']):
                uom_map.setdefault(row['name'], (row['id'], row['category_id'][0]))

            pos_ids_found = {row['id'] for row in _bulk_read(PosCateg, 'id', all_pos_ids, ['id'])}

            tax_map = {}
            for row in _bulk_read(Tax, 'name', all_tax_names, ['name']):
                tax_map.setdefault(row['name'], row['id'])

            # Merchandise Category yang sudah ada (termasuk arsip): vit_artikel_code -> row
            merch_existing = {}
            for row in _bulk_read(Merch.with_context(active_test=False), 'vit_artikel_code',
                                  all_merch_codes, MERCHANDISE_CATEGORY_FIELDS):
                merch_existing.setdefault(row['vit_artikel_code'], row)
            merch_done = {}  # vit_artikel_code -> (id, error) ; item pertama di payload yang menentukan

            def upsert_merch(code, data):
                """Find-or-create vit.merchandise.category dari field u_* di item.
                Kalau sudah ada, hanya field yang dikirim & berbeda yang di-update."""
                if code in merch_done:
                    return merch_done[code]
                vals = {}
                for field in MERCHANDISE_CATEGORY_FIELDS:
                    key, value = _payload_val(data, field)
                    if key:
                        vals[field] = value
                try:
                    with cr.savepoint():
                        _advisory_lock(cr, f"vit.merchandise.category:{code}")
                        row = merch_existing.get(code)
                        if row:
                            changed = {f: v for f, v in vals.items() if (row.get(f) or False) != (v or False)}
                            if changed:
                                Merch.browse(row['id']).write(changed)
                            result = (row['id'], None)
                        else:
                            result = (Merch.create(vals).id, None)
                except Exception as merch_err:
                    result = (None, f"Merchandise Category '{code}' failed: {merch_err}")
                merch_done[code] = result
                return result

            # ============================================================
            # 3. PROSES ITEM: CREATE (produk baru) / UPDATE (sudah ada,
            #    termasuk yang diarsipkan) / ARCHIVE (payload active=false)
            # ============================================================
            ProductUpd = env['product.template'].sudo().with_context(active_test=False)
            created, updated, errors = [], [], []
            pending = []            # [(product_code, vals), ...] untuk create
            seen_codes = set()      # deteksi kode dobel DI DALAM payload yang sama
            update_counter = 0

            def flush_pending():
                """Create 1 batch dalam savepoint; kalau batch gagal, ulangi
                satu-per-satu supaya hanya record bermasalah yang jadi error."""
                nonlocal pending
                if not pending:
                    return
                batch, pending = pending, []
                new_items = []
                try:
                    with cr.savepoint():
                        for code, _vals in batch:
                            _advisory_lock(cr, f"product.template:{code}")
                        recs = Product.create([vals for _code, vals in batch])
                    new_items = [{'id': r.id, 'product_code': r.default_code, 'name': r.name,
                                  'action': 'created'} for r in recs]
                except Exception as bulk_err:
                    _logger.warning(f"Bulk create produk gagal, fallback satu-per-satu: {bulk_err}")
                    for code, single_vals in batch:
                        try:
                            with cr.savepoint():
                                _advisory_lock(cr, f"product.template:{code}")
                                rec = Product.create(single_vals)
                            new_items.append({'id': rec.id, 'product_code': rec.default_code,
                                              'name': rec.name, 'action': 'created'})
                        except Exception as single_err:
                            errors.append({'id': -1, 'product_code': code,
                                           'message': f"Create failed: {single_err}"})
                _commit_with_retry(cr, context=f"item_create_{len(created) + len(new_items)}")
                created.extend(new_items)

            for data in items:
                try:
                    product_code = data.get('product_code')
                    if not product_code:
                        errors.append({'id': -1, 'product_code': None, 'message': "Missing product_code"})
                        continue

                    if product_code in seen_codes:
                        errors.append({'id': -1, 'product_code': product_code,
                                       'message': f"Duplicate item code in payload: {product_code}"})
                        continue
                    seen_codes.add(product_code)

                    existing_id = existing_ids.get(product_code)
                    is_new = not existing_id

                    # Category -- SEMENTARA tidak wajib: kalau kosong / tidak ditemukan,
                    # categ_id tidak diisi (produk baru -> kategori default All,
                    # produk lama -> kategori tidak diubah).
                    category_name = data.get('category_name')
                    category_id = categ_map.get(category_name) if category_name else False

                    # POS category & Tax: kalau ADA yang tidak ditemukan, item dilewati
                    # (semua kesalahan item ini tetap dilaporkan)
                    lookup_error = False
                    pos_ids = []
                    for cid in _as_list(data.get('pos_categ_ids', data.get('pos_categ_id', []))):
                        if cid in pos_ids_found:
                            pos_ids.append(cid)
                        else:
                            errors.append({'id': existing_id or -1, 'product_code': product_code,
                                           'message': f"POS category ID {cid} not found."})
                            lookup_error = True

                    tax_ids = []
                    for tax_name in _as_list(data.get('taxes_names', [])):
                        if tax_name in tax_map:
                            tax_ids.append(tax_map[tax_name])
                        else:
                            errors.append({'id': existing_id or -1, 'product_code': product_code,
                                           'message': f"Tax '{tax_name}' not found."})
                            lookup_error = True
                    if lookup_error:
                        continue

                    # UoM -- wajib untuk produk baru; untuk update opsional
                    # (kalau dikirim tetap harus valid)
                    uom_name = data.get('uom_name')
                    uom_po_name = data.get('uom_po_name')
                    if is_new:
                        if not uom_name:
                            errors.append({'id': -1, 'product_code': product_code, 'message': "uom_name missing"})
                            continue
                        if not uom_po_name:
                            errors.append({'id': -1, 'product_code': product_code, 'message': "uom_po_name missing"})
                            continue
                    uom = uom_map.get(uom_name) if uom_name else None
                    if uom_name and not uom:
                        errors.append({'id': existing_id or -1, 'product_code': product_code,
                                       'message': f"UoM '{uom_name}' not found."})
                        continue
                    uom_po = uom_map.get(uom_po_name) if uom_po_name else None
                    if uom_po_name and not uom_po:
                        errors.append({'id': existing_id or -1, 'product_code': product_code,
                                       'message': f"Purchase UoM '{uom_po_name}' not found."})
                        continue
                    if uom and uom_po and uom[1] != uom_po[1]:   # kategori UoM wajib sama
                        errors.append({'id': existing_id or -1, 'product_code': product_code,
                                       'message': "Default UoM and Purchase UoM must match."})
                        continue

                    if is_new and not data.get('product_name'):
                        errors.append({'id': -1, 'product_code': product_code,
                                       'message': "Missing product_name"})
                        continue

                    # Build vals -- field opsional hanya dikirim kalau ADA di payload,
                    # jadi update tidak menimpa field yang tidak dikirim.
                    vals = {}
                    if data.get('product_name'):
                        vals['name'] = data['product_name']
                    if 'standard_price' in data or 'cost' in data:
                        vals['standard_price'] = data.get('standard_price', data.get('cost', 0.0))
                    if uom:
                        vals['uom_id'] = uom[0]
                    if uom_po:
                        vals['uom_po_id'] = uom_po[0]
                    if category_id:
                        vals['categ_id'] = category_id
                    if is_new or 'pos_categ_ids' in data or 'pos_categ_id' in data:
                        vals['pos_categ_ids'] = [(6, 0, pos_ids)]
                    if is_new or 'taxes_names' in data:
                        vals['taxes_id'] = [(6, 0, tax_ids)]   # kosong = tanpa pajak
                    for payload_key, field_name in (
                        ('active',           'active'),         # false = ARCHIVE, true = unarchive
                        ('product_type',     'detailed_type'),
                        ('invoice_policy',   'invoice_policy'),
                        ('sales_price',      'list_price'),
                        ('available_in_pos', 'available_in_pos'),
                        ('barcode',          'barcode'),
                        ('image_1920',       'image_1920'),
                    ):
                        if payload_key in data:
                            vals[field_name] = data[payload_key]

                    # Merchandise Category (Many2one): dibentuk/di-update dari field item ini,
                    # kuncinya Artikel Code (vit_artikel_code, atau key lama U_VARC)
                    merch_code = _payload_val(data, 'vit_artikel_code')[1]
                    if merch_code:
                        merch_id, merch_err = upsert_merch(merch_code, data)
                        if merch_err:
                            errors.append({'id': existing_id or -1, 'product_code': product_code,
                                           'message': merch_err})
                            continue
                        vals['vit_merchandise_category_id'] = merch_id

                    if is_new:
                        # CREATE (per batch)
                        vals['default_code'] = product_code
                        vals['create_uid'] = uid   # sama seperti versi lama
                        pending.append((product_code, vals))
                        if len(pending) >= BATCH_CREATE_SIZE:
                            flush_pending()
                        continue

                    # UPDATE / ARCHIVE (savepoint + advisory lock per record)
                    # Ditandai belum terintegrasi supaya perubahan ikut sync ulang ke store.
                    vals.update({'is_integrated': False, 'index_store': [(5, 0, 0)]})
                    action = 'archived' if data.get('active') is False else (
                        'unarchived' if data.get('active') is True and not existing_active.get(existing_id, True)
                        else 'updated')
                    try:
                        with cr.savepoint():
                            _advisory_lock(cr, f"product.template.id:{existing_id}")
                            rec = ProductUpd.browse(existing_id)
                            rec.write(vals)
                        updated.append({'id': rec.id, 'product_code': rec.default_code,
                                        'name': rec.name, 'action': action})
                        update_counter += 1
                        if update_counter % BATCH_CREATE_SIZE == 0:
                            _commit_with_retry(cr, context=f"item_update_{update_counter}")
                    except Exception as upd_err:
                        errors.append({'id': existing_id, 'product_code': product_code,
                                       'message': f"Update failed: {upd_err}"})

                except Exception as e:
                    errors.append({'id': -1, 'product_code': data.get('product_code'), 'message': str(e)})

            flush_pending()   # sisa batch
            _commit_with_retry(cr, context="item_final")

            # ============================================================
            # RESPONSE
            # ============================================================
            if errors and (created or updated):
                code, status = 207, 'partial_success'
            elif created or updated:
                code, status = 200, 'success'
            else:
                code, status = 422, 'failed'

            return {
                'code':          code,
                'status':        status,
                'created_items': created,
                'updated_items': updated,
                'errors':        errors,
                'total_created': len(created),
                'total_updated': len(updated),
                'total_errors':  len(errors),
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Master Item API Fatal Error: {e}", exc_info=True)
            return {'status': 'Failed', 'code': 500, 'message': str(e)}



# controllers/master_pricelist.py
import logging
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# =========================================================
# KONFIGURASI BATCH
# =========================================================
PRODUCT_SEARCH_CHUNK = 5000      # jumlah default_code / id per query
LINE_CREATE_CHUNK    = 5000      # batch create items


def _chunks(values, size):
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i:i + size]


# =========================================================
# HELPER: SAVEPOINT
# =========================================================
def _savepoint(cr, name):
    cr.execute(f'SAVEPOINT "{name}"')


def _release(cr, name):
    cr.execute(f'RELEASE SAVEPOINT "{name}"')


def _rollback_to(cr, name):
    try:
        cr.execute(f'ROLLBACK TO SAVEPOINT "{name}"')
    except Exception:
        pass


class POSTMasterPricelist(http.Controller):

    # applied_on yang BERBASIS PRODUK. Nilai lain (2_product_category /
    # 3_global) membuat Odoo MENGOSONGKAN product_tmpl_id saat create.
    PRODUCT_APPLIED_ON = ('0_product_variant', '1_product')

    @http.route('/api/master_pricelist', type='json', auth='none', methods=['POST'], csrf=False)
    def post_pricelist(self, **kw):
        """
        API sinkronisasi pricelist dari SAP -- RIWAYAT HARGA:
        - Produk baru di pricelist  -> INSERT baris baru.
        - Harga/isi berubah         -> INSERT baris baru (berlaku mulai sekarang)
                                       + baris lama DITUTUP (date_end = sesaat
                                       sebelum baris baru mulai).
        - Isi sama                  -> tidak ada perubahan.
        Tidak pernah menghapus/menimpa baris lama.
        Pricelist dicari berdasarkan vit_code (per company).
        """
        try:
            # =========================================================
            # AUTHENTICATION (sama seperti endpoint lain)
            # =========================================================
            config = request.env['setting.config'].sudo().search([('vit_config_server', '=', 'mc')], limit=1)
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}

            uid = request.session.authenticate(request.session.db, config.vit_config_username,
                                               config.vit_config_password_api)
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)
            cr = request.env.cr

            Pricelist     = env['product.pricelist'].sudo()
            PricelistItem = env['product.pricelist.item'].sudo()
            Product       = env['product.product'].sudo()
            Currency      = env['res.currency'].sudo()
            Company       = env['res.company'].sudo()

            # =========================================================
            # DATA PREPARATION
            # =========================================================
            data = request.get_json_data()
            items = data.get('items', [])
            if isinstance(items, dict):
                items = [items]
            elif not isinstance(items, list):
                items = [data]

            if not items:
                return {'code': 400, 'status': 'Failed', 'message': 'No items provided.'}

            # =========================================================
            # GET ACTIVE COMPANIES
            # =========================================================
            companies = Company.search([('active', '=', True)])
            if not companies:
                return {'status': 'Failed', 'code': 404, 'message': 'No active companies found.'}
            company_ids = companies.ids

            # =========================================================
            # LANGKAH 1: Kumpulkan nilai unik dari payload
            # =========================================================
            all_product_codes = set()
            all_currency_ids  = set()
            all_vit_codes     = set()

            for item in items:
                if item.get('product_code'):
                    all_product_codes.add(item['product_code'])
                for price in item.get('prices', []) or []:
                    if price.get('vit_code'):
                        all_vit_codes.add(str(price['vit_code']))
                    if price.get('currency_id'):
                        all_currency_ids.add(price['currency_id'])

            if not all_vit_codes:
                return {'code': 400, 'status': 'Failed',
                        'message': 'No vit_code provided for pricelist in any item.'}

            # =========================================================
            # LANGKAH 2: Preload produk (chunked)
            # =========================================================
            product_map = {}
            for chunk_codes in _chunks(all_product_codes, PRODUCT_SEARCH_CHUNK):
                products = Product.search([
                    ('default_code', 'in', chunk_codes),
                    '|', ('company_id', 'in', company_ids), ('company_id', '=', False),
                ])
                for p in products:
                    product_map.setdefault((p.default_code, p.company_id.id or False), p.product_tmpl_id.id)

            def get_tmpl_id(code, company_id):
                return product_map.get((code, company_id)) or product_map.get((code, False))

            # =========================================================
            # LANGKAH 3: Preload pricelist berdasarkan vit_code
            # (TERMASUK yang diarsipkan, supaya tidak dibuat dobel).
            # Pricelist tanpa company (company_id kosong) dipakai sebagai
            # fallback untuk semua company.
            # =========================================================
            existing_pl_map = {}
            for pl in Pricelist.with_context(active_test=False).search([
                ('vit_code', 'in', list(all_vit_codes)),
                '|', ('company_id', 'in', company_ids), ('company_id', '=', False),
            ], order='active desc, id asc'):
                existing_pl_map.setdefault((pl.vit_code, pl.company_id.id or False), pl)

            def get_pricelist(vit_code, company_id):
                return existing_pl_map.get((vit_code, company_id)) or existing_pl_map.get((vit_code, False))

            # =========================================================
            # LANGKAH 4: Validasi currency
            # =========================================================
            valid_currencies = set(Currency.browse(list(all_currency_ids)).exists().filtered('active').ids)

            # =========================================================
            # LANGKAH 5: Bangun pricelist_data -- group by (vit_code, company_id)
            # =========================================================
            pricelist_data  = {}
            skipped         = []   # baris payload yang dilewati + alasannya
            # Odoo menyimpan datetime dalam UTC (di Windows datetime.now() = jam lokal)
            now      = datetime.utcnow().replace(microsecond=0)
            date_end = datetime(2099, 12, 31, 23, 59, 59)

            for item in items:
                product_code = item.get('product_code')
                if not product_code:
                    skipped.append({'product_code': None, 'message': 'Missing product_code'})
                    continue

                prices = item.get('prices', []) or []
                if not prices:
                    skipped.append({'product_code': product_code, 'message': 'No prices provided'})
                    continue

                quantity = item.get('quantity', 1)

                for price in prices:
                    vit_code    = str(price['vit_code']) if price.get('vit_code') else None
                    currency_id = price.get('currency_id')
                    if not vit_code or not currency_id:
                        skipped.append({'product_code': product_code, 'vit_code': vit_code,
                                        'message': 'vit_code / currency_id missing'})
                        continue
                    if currency_id not in valid_currencies:
                        skipped.append({'product_code': product_code, 'vit_code': vit_code,
                                        'message': f'Currency {currency_id} not found / inactive'})
                        continue

                    applied_on = price.get('conditions') or '1_product'
                    if applied_on not in self.PRODUCT_APPLIED_ON:
                        _logger.warning(f"[PRICELIST] {product_code}/{vit_code}: conditions="
                                        f"'{applied_on}' tidak berbasis produk, dipaksa '1_product'.")
                        applied_on = '1_product'

                    line_vals = {
                        'applied_on':    applied_on,
                        'compute_price': price.get('compute_price') or 'fixed',
                        'fixed_price':   float(price.get('fixed_price', 0.0) or 0.0),
                        'percent_price': float(price.get('percent_price', 0.0) or 0.0),
                        'min_quantity':  float(quantity or 0.0),
                    }

                    found_any = False
                    for company in companies:
                        cid = company.id
                        tmpl_id = get_tmpl_id(product_code, cid)
                        if not tmpl_id:
                            continue
                        found_any = True

                        key = (vit_code, cid)
                        if key not in pricelist_data:
                            pricelist_data[key] = {
                                'vit_code':      vit_code,
                                'company_id':    cid,
                                'company_name':  company.name,
                                'currency_id':   currency_id,
                                'name':          price.get('pricelist_name') or vit_code,
                                'active':        price.get('active', True),
                                'line_vals_map': {},   # tmpl_id -> line_vals
                            }
                        pricelist_data[key]['line_vals_map'][tmpl_id] = line_vals

                    if not found_any:
                        skipped.append({'product_code': product_code, 'vit_code': vit_code,
                                        'message': 'Product not found'})

            # =========================================================
            # LANGKAH 6: Preload baris yang SEDANG BERLAKU per
            # (pricelist, produk) -- yang belum berakhir, id TERBARU.
            # =========================================================
            all_pl_ids = list({
                pl.id for (vit_code, cid) in pricelist_data
                for pl in [get_pricelist(vit_code, cid)] if pl
            })

            current_line_map = {}  # (pricelist_id, tmpl_id) -> line dict
            if all_pl_ids:
                all_relevant_tmpl_ids = set()
                for d in pricelist_data.values():
                    all_relevant_tmpl_ids.update(d['line_vals_map'].keys())

                FIELDS = ['id', 'pricelist_id', 'product_tmpl_id', 'fixed_price', 'percent_price',
                          'compute_price', 'min_quantity', 'date_start', 'applied_on']
                for chunk_tmpl in _chunks(all_relevant_tmpl_ids, PRODUCT_SEARCH_CHUNK):
                    lines = PricelistItem.search_read([
                        ('pricelist_id', 'in', all_pl_ids),
                        ('product_tmpl_id', 'in', chunk_tmpl),
                        '|', ('date_end', '=', False), ('date_end', '>=', now),
                    ], fields=FIELDS, order='id desc')
                    for line in lines:
                        key = (line['pricelist_id'][0], line['product_tmpl_id'][0])
                        current_line_map.setdefault(key, line)  # id terbaru

            # =========================================================
            # LANGKAH 7: Proses tiap pricelist (savepoint per pricelist)
            # =========================================================
            COMPARE_FIELDS = ['fixed_price', 'percent_price', 'compute_price', 'min_quantity', 'applied_on']

            def _differs(old, new):
                if isinstance(new, float):
                    return abs((old or 0.0) - new) > 1e-6
                return old != new

            close_at = now - timedelta(seconds=1)

            created_pricelists = []
            updated_pricelists = []
            failed_pricelists  = []
            total_lines_created  = 0   # produk baru di pricelist
            total_lines_replaced = 0   # harga berubah -> baris baru + lama ditutup

            for pl_idx, ((vit_code, company_id), data_pl) in enumerate(pricelist_data.items()):
                sp = f'pl_{pl_idx}'   # nama savepoint aman (vit_code bisa berisi karakter apa saja)
                try:
                    _savepoint(cr, sp)

                    # --- Upsert header pricelist ---
                    pl_rec = get_pricelist(vit_code, company_id)
                    is_new_pl = not pl_rec
                    if is_new_pl:
                        pl_rec = Pricelist.create({
                            'vit_code':    vit_code,
                            'name':        data_pl['name'],
                            'currency_id': data_pl['currency_id'],
                            'company_id':  company_id,
                            'active':      data_pl['active'],
                        })
                        existing_pl_map[(vit_code, company_id)] = pl_rec
                        header_vals = {}
                    else:
                        header_vals = {}
                        if pl_rec.currency_id.id != data_pl['currency_id']:
                            header_vals['currency_id'] = data_pl['currency_id']
                        if pl_rec.name != data_pl['name']:
                            header_vals['name'] = data_pl['name']
                        if pl_rec.active != data_pl['active']:
                            header_vals['active'] = data_pl['active']

                    # --- Tentukan baris yang perlu di-INSERT & baris lama yang perlu DITUTUP ---
                    to_create      = []
                    to_close_ids   = []
                    replaced_count = 0

                    for tmpl_id, vals in data_pl['line_vals_map'].items():
                        current = current_line_map.get((pl_rec.id, tmpl_id))
                        if current and not any(_differs(current.get(f), vals.get(f)) for f in COMPARE_FIELDS):
                            continue  # tidak berubah -> tidak ada baris baru

                        to_create.append({
                            'pricelist_id':    pl_rec.id,
                            'product_tmpl_id': tmpl_id,
                            **vals,
                            'date_start':      now,
                            'date_end':        date_end,
                        })
                        if current:
                            to_close_ids.append(current['id'])
                            replaced_count += 1

                    # Ada perubahan -> tandai belum terintegrasi supaya ikut sync ulang ke store
                    if not is_new_pl and (header_vals or to_create):
                        header_vals.update({'is_integrated': False, 'index_store': [(5, 0, 0)]})
                    if header_vals:
                        pl_rec.write(header_vals)

                    # --- Tutup baris lama (berakhir sesaat sebelum baris baru mulai).
                    #     GREATEST: jaga date_end >= date_start. is_updated -> ikut sync ke store.
                    if to_close_ids:
                        cr.execute("""
                            UPDATE product_pricelist_item
                               SET date_end = GREATEST(COALESCE(date_start, %s), %s),
                                   is_updated = TRUE,
                                   write_date = (now() at time zone 'UTC')
                             WHERE id IN %s
                        """, (close_at, close_at, tuple(to_close_ids)))
                        PricelistItem.browse(to_close_ids).invalidate_recordset(['date_end', 'is_updated'])

                    # --- INSERT baris baru ---
                    for chunk in _chunks(to_create, LINE_CREATE_CHUNK):
                        new_lines = PricelistItem.create(chunk)
                        # Daftarkan sebagai baris berlaku, supaya produk dobel
                        # dalam payload yang sama tidak di-insert 2x
                        for nl, vals in zip(new_lines, chunk):
                            current_line_map[(pl_rec.id, nl.product_tmpl_id.id)] = {'id': nl.id, **vals}

                    total_lines_created  += len(to_create) - replaced_count
                    total_lines_replaced += replaced_count

                    info = {
                        'id':             pl_rec.id,
                        'vit_code':       vit_code,
                        'name':           pl_rec.name,
                        'company_id':     company_id,
                        'company_name':   data_pl['company_name'],
                        'lines_created':  len(to_create) - replaced_count,
                        'lines_replaced': replaced_count,
                    }
                    (created_pricelists if is_new_pl else updated_pricelists).append(info)

                    _release(cr, sp)
                    cr.commit()

                except Exception as e:
                    _rollback_to(cr, sp)
                    _logger.error(f"Error processing {vit_code} for company {company_id}: {e}", exc_info=True)
                    failed_pricelists.append({'vit_code': vit_code, 'company_id': company_id, 'message': str(e)})

            cr.commit()

            has_issue = bool(failed_pricelists or skipped)
            return {
                'code':   200 if not has_issue else 207,
                'status': 'success' if not has_issue else 'partial_success',
                'total_companies_processed': len(companies),
                'total_created_pricelists':  len(created_pricelists),
                'total_updated_pricelists':  len(updated_pricelists),
                'total_failed_pricelists':   len(failed_pricelists),
                'total_lines_created':       total_lines_created,
                'total_lines_replaced':      total_lines_replaced,
                'total_skipped':             len(skipped),
                'created_pricelists': created_pricelists,
                'updated_pricelists': updated_pricelists,
                'failed_pricelists':  failed_pricelists,
                'skipped':            skipped,
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Pricelist API Fatal Error: {e}", exc_info=True)
            return {'status': 'Failed', 'code': 500, 'message': str(e)}


class POSTMasterUoM(http.Controller):
    @http.route('/api/master_uom', type='json', auth='none', methods=['POST'], csrf=False)
    def post_master_uom(self, **kw):
        try:
            # 🔐 Autentikasi
            config = request.env['setting.config'].sudo().search(
                [('vit_config_server', '=', 'mc')], limit=1
            )
            if not config:
                return {
                    'status': 'Failed',
                    'code': 500,
                    'message': 'Configuration not found.'
                }

            uid = request.session.authenticate(
                request.session.db,
                config.vit_config_username,
                config.vit_config_password_api
            )
            if not uid:
                return {
                    'status': 'Failed',
                    'code': 401,
                    'message': 'Authentication failed.'
                }

            json_data = request.get_json_data()
            items = json_data.get('items')

            # ✅ Bisa single dict atau list
            if isinstance(items, dict):
                items = [items]
            elif items is None and isinstance(json_data, dict):
                items = [json_data]
            elif not isinstance(items, list):
                return {
                    'status': 'Failed',
                    'code': 400,
                    'message': "'items' must be a list or object."
                }

            vals_list, created, errors = [], [], []

            # 🔍 Validasi & kumpulkan data
            for data in items:
                try:
                    name = data.get('name')
                    uom_type = data.get('uom_type')
                    category_id = data.get('category_id')

                    if not name or not uom_type or not category_id:
                        errors.append({
                            'name': name,
                            'message': "Missing required field: name, uom_type, or category_id"
                        })
                        continue

                    # Cek duplikat berdasarkan name & category_id
                    existing = request.env['uom.uom'].sudo().search([
                        ('name', '=', name),
                        ('category_id', '=', category_id)
                    ], limit=1)
                    if existing:
                        errors.append({
                            'id': existing.id,
                            'name': name,
                            'message': f"Duplicate UoM with name '{name}' in this category"
                        })
                        continue

                    vals_list.append({
                        'name': name,
                        'uom_type': uom_type,
                        'category_id': category_id,
                        'rounding': data.get('rounding', 1.0),
                        'ratio': data.get('ratio', 1.0),
                        'active': data.get('active', True),
                        'factor': data.get('factor', 1.0),
                        'factor_inv': data.get('factor_inv', 1.0),
                    })

                except Exception as e:
                    errors.append({
                        'name': data.get('name'),
                        'message': f"Exception: {str(e)}"
                    })

            # 🚀 Bulk create
            if vals_list:
                uoms = request.env['uom.uom'].sudo().create(vals_list)
                for rec in uoms:
                    created.append({
                        'id': rec.id,
                        'name': rec.name,
                        'uom_type': rec.uom_type,
                        'category_id': rec.category_id.id,
                        'category': rec.category_id.name,
                        'status': 'success'
                    })

            return {
                'code': 200 if not errors else 207,
                'status': 'success' if not errors else 'partial_success',
                'created_uoms': created,
                'errors': errors
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create UoMs: {str(e)}")
            return {
                'status': 'Failed',
                'code': 500,
                'message': f"Failed to create UoMs: {str(e)}"
            }


class POSTMasterContact(http.Controller):
    @http.route('/api/master_contact', type='json', auth='none', methods=['POST'], csrf=False)
    def post_master_contact(self, **kw):
        try:
            # Autentikasi
            config = request.env['setting.config'].sudo().search(
                [('vit_config_server', '=', 'mc')], limit=1
            )
            if not config:
                return {'status': 'Failed', 'code': 500, 'message': 'Configuration not found.'}

            uid = request.session.authenticate(
                request.session.db,
                config.vit_config_username,
                config.vit_config_password_api
            )
            if not uid:
                return {'status': 'Failed', 'code': 401, 'message': 'Authentication failed.'}

            env = request.env(user=request.env.ref('base.user_admin').id)

            json_data = request.get_json_data()
            items = json_data.get('items') if isinstance(json_data, dict) else json_data

            # Bisa single dict atau list
            if isinstance(items, dict):
                items = [items]
            elif items is None and isinstance(json_data, dict):
                items = [json_data]
            elif not isinstance(items, list):
                return {'status': 'Failed', 'code': 400, 'message': "'items' must be a list or object."}

            VALID_TYPES = ['person', 'company']
            VALID_BP_TYPES = ['customer', 'vendor']

            Partner = env['res.partner'].sudo()
            Pricelist = env['product.pricelist'].sudo().with_context(active_test=False)
            companies = env['res.company'].sudo().search([('active', '=', True)])

            # =====================================================
            # PRICELIST HELPER
            # =====================================================
            pricelist_cache = {}

            def resolve_pricelists(vit_code):
                """Cari pricelist HANYA berdasarkan vit_code, TERMASUK yang
                di-archive, supaya tetap bisa dipasang dan otomatis tampil
                lagi saat pricelist diaktifkan kembali."""
                if vit_code in pricelist_cache:
                    return pricelist_cache[vit_code]
                pls = Pricelist.search([
                    ('vit_code', '=', vit_code),
                    '|', ('company_id', 'in', companies.ids), ('company_id', '=', False),
                ])
                pricelist_cache[vit_code] = pls
                return pls

            def apply_pricelist(partner, pricelists):
                """Pasang pricelist per company (specific_property_product_pricelist
                adalah field company-dependent). pricelists kosong = kosongkan."""
                if not pricelists:
                    for company in companies:
                        partner.with_company(company).specific_property_product_pricelist = False
                    return
                for company in companies:
                    pl = pricelists.filtered(lambda p: p.company_id == company)[:1] \
                        or pricelists.filtered(lambda p: not p.company_id)[:1]
                    if pl:
                        partner.with_company(company).specific_property_product_pricelist = pl

            def pricelist_info(partner):
                info = []
                for company in companies:
                    pl = partner.with_company(company).specific_property_product_pricelist
                    if pl:
                        info.append({
                            'company': company.name,
                            'pricelist': pl.vit_code or pl.name,
                            'active': pl.active,
                        })
                return info

            # =====================================================
            # BUILD RESULT HELPER
            # =====================================================
            def build_result(partner, action):
                return {
                    'id': partner.id,
                    'vit_customer_vendor_code': partner.vit_customer_vendor_code,
                    'name': partner.name,
                    'vit_bp_type': partner.vit_bp_type,
                    'telp1': partner.phone,
                    'contactname': partner.function,
                    'email': partner.email,
                    'npwp': partner.vat,
                    'type': partner.company_type,
                    'pricelists': pricelist_info(partner),
                    'status': action
                }

            vals_list, created, updated, errors = [], [], [], []
            seen_codes = set()

            # =====================================================
            # PROCESS EACH ITEM
            # =====================================================
            for data in items:
                try:
                    vit_customer_vendor_code = data.get('vit_customer_vendor_code')
                    if not vit_customer_vendor_code:
                        errors.append({
                            'vit_customer_vendor_code': None,
                            'message': "Missing vit_customer_vendor_code"
                        })
                        continue

                    if vit_customer_vendor_code in seen_codes:
                        errors.append({
                            'vit_customer_vendor_code': vit_customer_vendor_code,
                            'message': "Duplicate vit_customer_vendor_code in payload"
                        })
                        continue
                    seen_codes.add(vit_customer_vendor_code)

                    name = data.get('name')
                    if not name:
                        errors.append({
                            'vit_customer_vendor_code': vit_customer_vendor_code,
                            'message': "Missing name"
                        })
                        continue

                    # Validasi company type (person/company)
                    company_type = (data.get('type') or 'company').lower()
                    if company_type not in VALID_TYPES:
                        errors.append({
                            'vit_customer_vendor_code': vit_customer_vendor_code,
                            'message': f"Invalid 'type'. Valid values: {', '.join(VALID_TYPES)}"
                        })
                        continue

                    # Validasi vit_bp_type (customer/vendor)
                    vit_bp_type = (data.get('vit_bp_type') or '').lower()
                    if not vit_bp_type:
                        errors.append({
                            'vit_customer_vendor_code': vit_customer_vendor_code,
                            'message': "Missing 'vit_bp_type'. Valid values: customer, vendor"
                        })
                        continue
                    if vit_bp_type not in VALID_BP_TYPES:
                        errors.append({
                            'vit_customer_vendor_code': vit_customer_vendor_code,
                            'message': f"Invalid 'vit_bp_type'. Valid values: {', '.join(VALID_BP_TYPES)}"
                        })
                        continue

                    # =====================================================
                    # VALIDASI PRICELIST (opsional)
                    #   - key tidak dikirim  -> pricelist tidak diubah
                    #   - "" / null          -> pricelist dikosongkan
                    #   - vit_code           -> dipasang
                    # =====================================================
                    set_pricelist = 'property_product_pricelist' in data
                    pricelists = env['product.pricelist']
                    if set_pricelist and data.get('property_product_pricelist'):
                        pl_code = str(data['property_product_pricelist']).strip()
                        pricelists = resolve_pricelists(pl_code)
                        if not pricelists:
                            errors.append({
                                'vit_customer_vendor_code': vit_customer_vendor_code,
                                'message': f"Pricelist '{pl_code}' not found"
                            })
                            continue

                    # =====================================================
                    # CHECK EXISTING (kode baru, fallback customer_code lama)
                    # =====================================================
                    existing = Partner.search(
                        [('vit_customer_vendor_code', '=', vit_customer_vendor_code)], limit=1
                    ) or Partner.search(
                        [('customer_code', '=', vit_customer_vendor_code)], limit=1
                    )

                    # =====================================================
                    # PREPARE VALUES
                    # =====================================================
                    customer_vals = {
                        'name': name,
                        'vit_customer_vendor_code': vit_customer_vendor_code,
                        'vit_bp_type': vit_bp_type,
                        'customer_rank': 1 if vit_bp_type == 'customer' else 0,
                        'supplier_rank': 1 if vit_bp_type == 'vendor' else 0,
                        'phone': data.get('telp1'),
                        'email': data.get('email'),
                        'vat': data.get('npwp'),
                        'company_type': company_type,
                        # tandai belum terintegrasi supaya ikut sync MC -> SS
                        'is_integrated': False,
                        'index_store': [(5, 0, 0)],
                    }
                    # Sync MC -> SS mencocokkan res.partner lewat customer_code,
                    # jadi customer otomatis diberi customer_code = kode SAP.
                    if vit_bp_type == 'customer':
                        customer_vals['customer_code'] = vit_customer_vendor_code

                    contact_name = data.get('contactname')
                    if contact_name is not None:
                        customer_vals['function'] = contact_name

                    # =====================================================
                    # CREATE OR UPDATE
                    # =====================================================
                    if existing:
                        existing.write(customer_vals)
                        if set_pricelist:
                            apply_pricelist(existing, pricelists)
                        updated.append(build_result(existing, 'updated'))
                    else:
                        customer_vals['create_uid'] = uid
                        vals_list.append((customer_vals, set_pricelist, pricelists))

                except Exception as e:
                    errors.append({
                        'vit_customer_vendor_code': data.get('vit_customer_vendor_code'),
                        'message': f"Exception: {str(e)}"
                    })

            # =====================================================
            # BULK CREATE
            # =====================================================
            if vals_list:
                customers = Partner.create([v for v, _, _ in vals_list])
                for rec, (_, set_pricelist, pricelists) in zip(customers, vals_list):
                    if set_pricelist:
                        apply_pricelist(rec, pricelists)
                    created.append(build_result(rec, 'created'))

            return {
                'code': 200 if not errors else 207,
                'status': 'success' if not errors else 'partial_success',
                'summary': {
                    'total': len(items),
                    'created': len(created),
                    'updated': len(updated),
                    'failed': len(errors)
                },
                'created': created,
                'updated': updated,
                'errors': errors
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to process contacts: {str(e)}", exc_info=True)
            return {'status': 'Failed', 'code': 500, 'message': f"Failed to process contacts: {str(e)}"}


class POSTMasterWarehouse(http.Controller):
    @http.route('/api/master_warehouse', type='json', auth='none', methods=['POST'], csrf=False)
    def post_master_warehouse(self, **kw):
        try:
            # Authentication
            config = request.env['setting.config'].sudo().search([('vit_config_server', '=', 'mc')], limit=1)
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}
            
            uid = request.session.authenticate(request.session.db, config.vit_config_username, config.vit_config_password_api)
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)
            
            data = data = request.get_json_data()
            code = data.get('code')

            if env['stock.warehouse'].sudo().search([('code', '=', code)], limit=1):
                return {'status': "Failed", 'code': 400, 'message': f"Duplicate Warehouse code: {code}"}

            warehouse_data = {
                'name': data.get('name'),
                'code': code,
                'create_uid': uid
            }

            warehouse = env['stock.warehouse'].sudo().create(warehouse_data)
            
            return {
                'code': 200,
                'status': 'success',
                'message': 'Warehouse created successfully',
                'id': warehouse.id,
            }
        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create Warehouse: {str(e)}")
            return {'status': "Failed", 'code': 500, 'message': f"Failed to create Warehouse: {str(e)}"}
    
class POSTItemCategory(http.Controller):
    @http.route('/api/item_category', type='json', auth='none', methods=['POST'], csrf=False)
    def post_item_group(self, **kw):
        try:
            # Authentication
            config = request.env['setting.config'].sudo().search([('vit_config_server', '=', 'mc')], limit=1)
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}
            
            uid = request.session.authenticate(request.session.db, config.vit_config_username, config.vit_config_password_api)
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)
            
            data = data = request.get_json_data()
            category_name = data.get('category_name')

            if env['product.category'].sudo().search([('name', '=', category_name)], limit=1):
                return {'status': "Failed", 'code': 400, 'message': f"Duplicate category name: {category_name}."}

            category_data = {
                'name': category_name,
                'parent_id': data.get('parent_category_id'),
                'property_cost_method': data.get('costing_method'),
                'create_date': data.get('create_date'),
                'create_uid': uid
            }

            category = env['product.category'].sudo().create(category_data)
            
            return {
                'code': 200,
                'status': 'success',
                'message': 'Item Category created successfully',
                'id': category.id,
            }
        
        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create Category: {str(e)}")
            return {'status': "Failed", 'code': 500, 'message': f"Failed to create Category: {str(e)}"}

class POSTItemPoSCategory(http.Controller):
    @http.route('/api/pos_category', type='json', auth='none', methods=['POST'], csrf=False)
    def post_pos_category(self, **kw):
        try:
            # Authentication
            config = request.env['setting.config'].sudo().search([('vit_config_server', '=', 'mc')], limit=1)
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}
            
            uid = request.session.authenticate(request.session.db, config.vit_config_username, config.vit_config_password_api)
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)
            
            data = data = request.get_json_data()
            category_name = data.get('category_name')

            if env['pos.category'].sudo().search([('name', '=', category_name)], limit=1):
                return {'status': "Failed", 'code': 400, 'message': f"Duplicate PoS category name: {category_name}."}

            category_data = {
                'name': category_name,
                'create_date': data.get('create_date'),
                'create_uid': uid
            }

            category = env['pos.category'].sudo().create(category_data)
            
            return {
                'code': 200,
                'status': 'success',
                'message': 'PoS Category created successfully',
                'id': category.id,
            }
        
        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create PoS Category: {str(e)}")
            return {'status': "Failed", 'code': 500, 'message': f"Failed to create PoS Category: {str(e)}"}
        
class POSTGoodsReceipt(http.Controller):
    @http.route('/api/goods_receipt', type='json', auth='none', methods=['POST'], csrf=False)
    def post_goods_receipt(self, **kw):
        try:
            # Authentication
            config = request.env['setting.config'].sudo().search([('vit_config_server', '=', 'mc')], limit=1)
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}
            
            uid = request.session.authenticate(request.session.db, config.vit_config_username, config.vit_config_password_api)
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)
            
            data = request.get_json_data()
            picking_type_name = data.get('picking_type')
            location_id = data.get('location_id')
            location_dest_id = data.get('location_dest_id')
            scheduled_date = data.get('scheduled_date')
            date_done = data.get('date_done')
            transaction_id = data.get('transaction_id')
            move_type = data.get('move_type')
            move_lines = data.get('move_lines', [])

            # Validate if Goods Receipt already exists
            existing_goods_receipts = env['stock.picking'].sudo().search([
                ('vit_trxid', '=', transaction_id), 
                ('picking_type_id.name', '=', 'Goods Receipts')
            ], limit=1)
            
            if existing_goods_receipts:   
                return {
                    'code': 400,
                    'status': 'failed',
                    'message': 'Goods Receipt already exists',
                    'id': existing_goods_receipts.id,
                    'doc_num': existing_goods_receipts.name
                }

            # Validate picking type
            picking_type = env['stock.picking.type'].sudo().search([('name', '=', picking_type_name)], limit=1)
            if not picking_type:
                return {
                    'status': "Failed", 
                    'code': 400, 
                    'message': f"Picking type '{picking_type_name}' not found."
                }

            # Validate locations
            source_location = env['stock.location'].sudo().browse(location_id)
            dest_location = env['stock.location'].sudo().browse(location_dest_id)
            
            if not source_location.exists():
                return {
                    'status': "Failed", 
                    'code': 400, 
                    'message': f"Source location with ID {location_id} not found."
                }
            
            if not dest_location.exists():
                return {
                    'status': "Failed", 
                    'code': 400, 
                    'message': f"Destination location with ID {location_dest_id} not found."
                }

            # Validate all products first before creating Goods Receipt
            missing_products = []
            for line in move_lines:
                product_code = line.get('product_code')
                product_id = env['product.product'].sudo().search([('default_code', '=', product_code)], limit=1)
                if not product_id:
                    missing_products.append(product_code)

            if missing_products:
                return {
                    'status': "Failed",
                    'code': 400,
                    'message': f"Products with codes {', '.join(missing_products)} not found. Goods Receipt creation cancelled."
                }

            # Create Goods Receipt
            goods_receipt = env['stock.picking'].sudo().create({
                'picking_type_id': picking_type.id,
                'location_id': location_dest_id,
                'location_dest_id': location_id,
                'move_type': move_type,
                'scheduled_date': scheduled_date,
                'date_done': date_done,
                'vit_trxid': transaction_id,
                'create_uid': uid,
                # 'immediate_transfer': True  # Added to ensure immediate transfer
            })

            # Create move lines
            move_line_vals = []
            for line in move_lines:
                product_code = line.get('product_code')
                product_uom_qty = line.get('product_uom_qty')
                product_id = env['product.product'].sudo().search([('default_code', '=', product_code)], limit=1)

                move_vals = {
                    'name': product_id.name,
                    'product_id': product_id.id,
                    'product_uom': product_id.uom_id.id,  # Added product UOM
                    'product_uom_qty': float(product_uom_qty),
                    'quantity': float(product_uom_qty),  # Added to ensure validation
                    'picking_id': goods_receipt.id,
                    'location_id': location_id,
                    'location_dest_id': location_dest_id,
                    'state': 'draft',
                }
                move_line_vals.append((0, 0, move_vals))

            # Update goods receipt with move lines
            goods_receipt.write({
                'move_ids_without_package': move_line_vals
            })

            try:
                # Validate the goods receipt
                goods_receipt.button_validate()
            except Exception as validate_error:
                env.cr.rollback()
                # If validation fails, delete the goods receipt and return error
                goods_receipt.sudo().unlink()
                raise Exception(f"Failed to validate Goods Receipt: {str(validate_error)}")

            return {
                'code': 200,
                'status': 'success',
                'message': 'Goods Receipt created and validated successfully',
                'id': goods_receipt.id,
                'doc_num': goods_receipt.name
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create Goods Receipt: {str(e)}", exc_info=True)
            return {
                'status': "Failed", 
                'code': 500, 
                'message': f"Failed to create Goods Receipt: {str(e)}"
            }

class POSTGoodsIssue(http.Controller):
    @http.route('/api/goods_issue', type='json', auth='none', methods=['POST'], csrf=False)
    def post_goods_issue(self, **kw):
        try:
            # Authentication
            config = request.env['setting.config'].sudo().search([('vit_config_server', '=', 'mc')], limit=1)
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}
            
            uid = request.session.authenticate(request.session.db, config.vit_config_username, config.vit_config_password_api)
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)
            
            data = request.get_json_data()
            picking_type_name = data.get('picking_type')
            location_id = data.get('location_id')
            location_dest_id = data.get('location_dest_id')
            scheduled_date = data.get('scheduled_date')
            date_done = data.get('date_done')
            transaction_id = data.get('transaction_id')
            move_type = data.get('move_type')
            move_lines = data.get('move_lines', [])

            # Validate if Goods Issue already exists
            existing_goods_issue = env['stock.picking'].sudo().search([
                ('vit_trxid', '=', transaction_id), 
                ('picking_type_id.name', '=', 'Goods Issue')
            ], limit=1)
            
            if existing_goods_issue:    
                return {
                    'code': 400,
                    'status': 'failed',
                    'message': 'Goods Issue already exists',
                    'id': existing_goods_issue.id,
                    'doc_num': existing_goods_issue.name
                }         

            # Validate picking type
            picking_type = env['stock.picking.type'].sudo().search([('name', '=', picking_type_name)], limit=1)
            if not picking_type:
                return {
                    'status': "Failed", 
                    'code': 400, 
                    'message': f"Picking type '{picking_type_name}' not found."
                }

            # Validate locations
            source_location = env['stock.location'].sudo().browse(location_id)
            dest_location = env['stock.location'].sudo().browse(location_dest_id)
            
            if not source_location.exists():
                return {
                    'status': "Failed", 
                    'code': 400, 
                    'message': f"Source location with ID {location_id} not found."
                }
            
            if not dest_location.exists():
                return {
                    'status': "Failed", 
                    'code': 400, 
                    'message': f"Destination location with ID {location_dest_id} not found."
                }

            # Validate all products first before creating Goods Issue
            missing_products = []
            for line in move_lines:
                product_code = line.get('product_code')
                product_id = env['product.product'].sudo().search([('default_code', '=', product_code)], limit=1)
                if not product_id:
                    missing_products.append(product_code)

            if missing_products:
                return {
                    'status': "Failed",
                    'code': 400,
                    'message': f"Products with codes {', '.join(missing_products)} not found. Goods Issue creation cancelled."
                }

            # Create Goods Issue
            goods_issue = env['stock.picking'].sudo().create({
                'picking_type_id': picking_type.id,
                'location_id': location_id,
                'location_dest_id': location_dest_id,
                'move_type': move_type,
                'scheduled_date': scheduled_date,
                'date_done': date_done,
                'vit_trxid': transaction_id,
                'create_uid': uid,
                # 'immediate_transfer': True  # Added to ensure immediate transfer
            })

            # Create move lines
            move_line_vals = []
            for line in move_lines:
                product_code = line.get('product_code')
                product_uom_qty = line.get('product_uom_qty')
                product_id = env['product.product'].sudo().search([('default_code', '=', product_code)], limit=1)

                move_vals = {
                    'name': product_id.name,
                    'product_id': product_id.id,
                    'product_uom': product_id.uom_id.id,  # Added product UOM
                    'product_uom_qty': product_uom_qty,
                    'quantity': product_uom_qty,  # Added to ensure validation
                    'picking_id': goods_issue.id,
                    'location_id': location_id,
                    'location_dest_id': location_dest_id,
                    'state': 'draft',
                }
                move_line_vals.append((0, 0, move_vals))

            # Update goods issue with move lines
            goods_issue.write({
                'move_ids_without_package': move_line_vals
            })

            try:
                # Validate the goods issue
                goods_issue.button_validate()
            except Exception as validate_error:
                env.cr.rollback()
                # If validation fails, delete the goods issue and return error
                goods_issue.sudo().unlink()
                raise Exception(f"Failed to validate Goods Issue: {str(validate_error)}")

            return {
                'code': 200,
                'status': 'success',
                'message': 'Goods Issue created and validated successfully',
                'id': goods_issue.id,
                'doc_num': goods_issue.name
            }
            
        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create Goods Issue: {str(e)}", exc_info=True)
            return {
                'status': "Failed", 
                'code': 500, 
                'message': f"Failed to create Goods Issue: {str(e)}"
            }
        
class POSTPurchaseOrderFromSAP(http.Controller):
    @http.route('/api/purchase_order', type='json', auth='none', methods=['POST'], csrf=False)
    def post_purchase_order(self, **kw):
        try:
            # 🔐 Authentication
            config = request.env['setting.config'].sudo().search(
                [('vit_config_server', '=', 'mc')], limit=1
            )
            if not config:
                return {'status': "Failed", 'code': 500, 'message': "Configuration not found."}

            uid = request.session.authenticate(
                request.session.db,
                config.vit_config_username,
                config.vit_config_password_api
            )
            if not uid:
                return {'status': "Failed", 'code': 401, 'message': "Authentication failed."}

            env = request.env(user=request.env.ref('base.user_admin').id)

            # 📥 Get JSON payload
            data = request.get_json_data()
            customer_code = data.get('customer_code')
            vendor_reference = data.get('vendor_reference')
            currency_name = data.get('currency_id')        # nama currency, ex: "IDR"
            date_order = data.get('date_order')
            transaction_id = data.get('transaction_id')
            expected_arrival = data.get('expected_arrival')
            picking_type_name = data.get('picking_type')
            location_id = data.get('location_id')
            order_line = data.get('order_line', [])

            # 🔎 Check duplicate PO
            existing_po = env['purchase.order'].sudo().search([
                ('vit_trxid', '=', transaction_id),
                ('picking_type_id.name', '=', picking_type_name),
                ('picking_type_id.default_location_dest_id', '=', location_id)
            ], limit=1)

            if existing_po:
                return {
                    'code': 500,
                    'status': 'failed',
                    'message': 'Purchase Order already exists',
                    'id': existing_po.id,
                }

            # 🔎 Validate customer
            customer_id = env['res.partner'].sudo().search(
                [('customer_code', '=', customer_code)], limit=1
            ).id
            if not customer_id:
                return {
                    'status': "Failed",
                    'code': 500,
                    'message': f"Customer with code '{customer_code}' not found.",
                }

            # 🔎 Validate currency
            currency = env['res.currency'].sudo().search([('name', '=', currency_name)], limit=1)
            if not currency:
                return {
                    'status': "Failed",
                    'code': 500,
                    'message': f"Currency with name '{currency_name}' not found.",
                }
            currency_id = currency.id

            # 🔎 Validate picking type
            picking_types = env['stock.picking.type'].sudo().search([
                ('name', '=', picking_type_name),
                ('default_location_dest_id', '=', location_id)
            ], limit=1)

            if not picking_types:
                return {
                    'status': "Failed",
                    'code': 500,
                    'message': f"Picking type with name '{picking_type_name}' and location_id '{location_id}' not found.",
                }

            # 🔎 Validate all products first
            missing_products = []
            for line in order_line:
                product_code = line.get('product_code')
                product_id = env['product.product'].sudo().search(
                    [('default_code', '=', product_code)], limit=1
                )
                if not product_id:
                    missing_products.append(product_code)

            if missing_products:
                return {
                    'status': "Failed",
                    'code': 500,
                    'message': f"Products with codes {', '.join(missing_products)} not found. Purchase Order creation cancelled.",
                }

            # 🧾 Build purchase order lines
            purchase_order_lines = []
            for line in order_line:
                product_code = line.get('product_code')
                product_uom_qty = line.get('product_uom_qty')
                price_unit = line.get('price_unit')
                taxes_name = line.get('taxes_ids')
                vit_line_number_sap = line.get('line_number_sap')

                # Validate tax
                tax = env['account.tax'].sudo().search([('name', '=', taxes_name)], limit=1)
                if not tax:
                    return {
                        'status': "Failed",
                        'code': 500,
                        'message': f"Failed to create PO. Tax not found: {taxes_name}.",
                    }

                product_id = env['product.product'].sudo().search(
                    [('default_code', '=', product_code)], limit=1
                )

                purchase_order_line = {
                    'name': product_id.name,
                    'product_id': product_id.id,
                    'product_qty': product_uom_qty,
                    'price_unit': price_unit,
                    'taxes_id': [(6, 0, [tax.id])],
                    'vit_line_number_sap': vit_line_number_sap,
                    'product_uom': product_id.uom_id.id,
                }
                purchase_order_lines.append((0, 0, purchase_order_line))

            # 📝 Create purchase order
            purchase_order = env['purchase.order'].sudo().create({
                'partner_id': customer_id,
                'partner_ref': vendor_reference,
                'currency_id': currency_id,
                'date_order': date_order,
                'date_planned': expected_arrival,
                'vit_trxid': transaction_id,
                'picking_type_id': picking_types.id,
                'create_uid': uid,
                'user_id': uid,
                'order_line': purchase_order_lines,
            })

            # ✅ Confirm purchase order
            purchase_order.button_confirm()

            # 🔄 Update related pickings
            picking_ids = env['stock.picking'].sudo().search([('purchase_id', '=', purchase_order.id)])
            if picking_ids:
                for picking in picking_ids:
                    for move in picking.move_ids_without_package:
                        move.product_uom_qty = move.quantity
                    picking.write({
                        'origin': purchase_order.name,
                        'vit_trxid': transaction_id
                    })

            return {
                'code': 200,
                'status': 'success',
                'message': 'Purchase created and validated successfully',
                'id': purchase_order.id,
                'doc_num': purchase_order.name
            }

        except Exception as e:
            request.env.cr.rollback()
            _logger.error(f"Failed to create Purchase Order: {str(e)}", exc_info=True)
            return {
                'status': "Failed",
                'code': 500,
                'message': f"Failed to create Purchase Order: {str(e)}",
            }