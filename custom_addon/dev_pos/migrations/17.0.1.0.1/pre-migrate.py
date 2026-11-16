"""Rename kolom Merchandise Category u_v* -> vit_* tanpa kehilangan data.

Jalan otomatis saat upgrade modul dari versi < 17.0.1.0.1.
Kolom lama di-rename (bukan dibuat baru), jadi isi data tetap.
Kalau kolom lama tidak ada (DB baru / belum pernah upgrade), dilewati.
"""
import logging

_logger = logging.getLogger(__name__)

RENAMES = [
    ('u_varc', 'vit_artikel_code'), ('u_vszr', 'vit_size_range'), ('u_vmcc', 'vit_mc_code'),
    ('u_vifc', 'vit_flag_code'), ('u_vifn', 'vit_flag'),
    ('u_vstc', 'vit_style_code'), ('u_vstn', 'vit_style'),
    ('u_vscc', 'vit_sub_category_code'), ('u_vscn', 'vit_sub_category'),
    ('u_vctc', 'vit_category_code'), ('u_vctn', 'vit_category'),
    ('u_vsbc', 'vit_sub_brand_code'), ('u_vsbn', 'vit_sub_brand'),
    ('u_vbrc', 'vit_brand_code'), ('u_vbrn', 'vit_brand'),
    ('u_vcrc', 'vit_color_code'), ('u_vcrn', 'vit_color'),
    ('u_vszc', 'vit_size_code'), ('u_vszn', 'vit_size'),
    ('u_vlbc', 'vit_label_code'), ('u_vlbn', 'vit_label'),
    ('u_vwkc', 'vit_week_code'), ('u_vwkn', 'vit_week'),
    ('u_vqtc', 'vit_quarter_code'), ('u_vqtn', 'vit_quarter'),
    ('u_vctn_collection', 'vit_collection'),
    ('u_vuby', 'vit_upload_by'), ('u_vefn', 'vit_excel_filename'),
]

# tabel -> model (untuk update ir_model_fields)
TABLES = {
    'vit_merchandise_category': 'vit.merchandise.category',
    'product_template': 'product.template',
    'product_product': 'product.product',
}


def _column_exists(cr, table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                  WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version:
        return
    for table, model in TABLES.items():
        for old, new in RENAMES:
            if not _column_exists(cr, table, old) or _column_exists(cr, table, new):
                continue
            cr.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')
            # Ganti juga metadata field supaya tidak dihapus/dibuat ulang oleh Odoo
            cr.execute("UPDATE ir_model_fields SET name = %s WHERE model = %s AND name = %s",
                       (new, model, old))
            old_xmlid = f"field_{model.replace('.', '_')}__{old}"
            new_xmlid = f"field_{model.replace('.', '_')}__{new}"
            cr.execute("""UPDATE ir_model_data SET name = %s
                          WHERE module = 'dev_pos' AND model = 'ir.model.fields' AND name = %s""",
                       (new_xmlid, old_xmlid))
            _logger.info("Renamed %s.%s -> %s", table, old, new)

    # Constraint unik lama diganti nama baru (vit_artikel_code_unique) oleh Odoo
    cr.execute("""ALTER TABLE IF EXISTS vit_merchandise_category
                  DROP CONSTRAINT IF EXISTS vit_merchandise_category_u_varc_unique""")
