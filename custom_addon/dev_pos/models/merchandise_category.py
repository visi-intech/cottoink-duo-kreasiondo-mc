from odoo import models, fields, api, _

# Semua field data master Merchandise Category (urutan sesuai spec SAP).
# Dipakai oleh sync MC->SS (data_integrator) dan API GET/POST.
MERCHANDISE_CATEGORY_FIELDS = [
    'vit_artikel_code', 'vit_size_range', 'vit_mc_code', 'vit_flag_code', 'vit_flag', 'vit_style_code', 'vit_style',
    'vit_sub_category_code', 'vit_sub_category', 'vit_category_code', 'vit_category', 'vit_sub_brand_code', 'vit_sub_brand', 'vit_brand_code',
    'vit_brand', 'vit_color_code', 'vit_color', 'vit_size_code', 'vit_size', 'vit_label_code', 'vit_label',
    'vit_week_code', 'vit_week', 'vit_quarter_code', 'vit_quarter', 'vit_collection', 'vit_upload_by',
    'vit_excel_filename',
]

# Key lama (kode UDF SAP) yang masih diterima API POST supaya payload SAP lama tetap jalan.
# Payload boleh pakai nama field baru (vit_artikel_code) atau key lama (U_VARC / u_varc).
MERCHANDISE_CATEGORY_LEGACY_KEYS = {
    'vit_artikel_code': 'U_VARC', 'vit_size_range': 'U_VSZR', 'vit_mc_code': 'U_VMCC',
    'vit_flag_code': 'U_VIFC', 'vit_flag': 'U_VIFN',
    'vit_style_code': 'U_VSTC', 'vit_style': 'U_VSTN',
    'vit_sub_category_code': 'U_VSCC', 'vit_sub_category': 'U_VSCN',
    'vit_category_code': 'U_VCTC', 'vit_category': 'U_VCTN',
    'vit_sub_brand_code': 'U_VSBC', 'vit_sub_brand': 'U_VSBN',
    'vit_brand_code': 'U_VBRC', 'vit_brand': 'U_VBRN',
    'vit_color_code': 'U_VCRC', 'vit_color': 'U_VCRN',
    'vit_size_code': 'U_VSZC', 'vit_size': 'U_VSZN',
    'vit_label_code': 'U_VLBC', 'vit_label': 'U_VLBN',
    'vit_week_code': 'U_VWKC', 'vit_week': 'U_VWKN',
    'vit_quarter_code': 'U_VQTC', 'vit_quarter': 'U_VQTN',
    'vit_collection': 'U_VCTN_COLLECTION',  # di spec SAP juga U_VCTN (bentrok dgn Category Name)
    'vit_upload_by': 'U_VUBY', 'vit_excel_filename': 'U_VEFN',
}

# Field yang ditampilkan ulang (related, stored) di product.template / product.product.
# Upload By & Excel FileName hanya info upload, cukup di master.
MERCHANDISE_CATEGORY_PRODUCT_FIELDS = [
    f for f in MERCHANDISE_CATEGORY_FIELDS if f not in ('vit_upload_by', 'vit_excel_filename')
]


class VitMerchandiseCategory(models.Model):
    _name = 'vit.merchandise.category'
    _description = 'Merchandise Category'
    _inherit = ['mail.thread']
    # PENTING: _rec_name = field unik di data_integrator ('vit_artikel_code').
    # data_integrator memetakan Many2one lewat display_name sumber == field unik target,
    # jadi display_name jangan dioverride.
    _rec_name = 'vit_artikel_code'
    _order = 'vit_artikel_code'

    vit_artikel_code = fields.Char(string="Artikel Code", size=50, required=True, index=True, tracking=True)
    vit_size_range = fields.Char(string="Size Range", size=50)
    vit_mc_code = fields.Char(string="MC Code", size=20)
    vit_flag_code = fields.Char(string="Flag Code", size=5)
    vit_flag = fields.Char(string="Flag Name", size=100)
    vit_style_code = fields.Char(string="Style Code", size=5)
    vit_style = fields.Char(string="Style Name", size=100)
    vit_sub_category_code = fields.Char(string="Sub Category Code", size=5)
    vit_sub_category = fields.Char(string="Sub Category Name", size=100)
    vit_category_code = fields.Char(string="Category Code", size=5)
    vit_category = fields.Char(string="Category Name", size=100)
    vit_sub_brand_code = fields.Char(string="Sub Brand Code", size=5)
    vit_sub_brand = fields.Char(string="Sub Brand Name", size=100)
    vit_brand_code = fields.Char(string="Brand Code", size=5)
    vit_brand = fields.Char(string="Brand Name", size=100)
    vit_color_code = fields.Char(string="Color Code", size=5)
    vit_color = fields.Char(string="Color Name", size=100)
    vit_size_code = fields.Char(string="Size Code", size=5)
    vit_size = fields.Char(string="Size Name", size=100)
    vit_label_code = fields.Char(string="Label Code", size=5)
    vit_label = fields.Char(string="Label Name", size=100)
    vit_week_code = fields.Char(string="Week Code", size=5)
    vit_week = fields.Char(string="Week Name", size=100)
    vit_quarter_code = fields.Char(string="Quarter Code", size=5)
    vit_quarter = fields.Char(string="Quarter Name", size=100)
    vit_collection = fields.Char(string="Collection Name", size=200)
    vit_upload_by = fields.Char(string="Upload By", size=200)
    vit_excel_filename = fields.Char(string="Excel FileName", size=254)

    active = fields.Boolean(default=True)

    # ── Integrasi MC -> SS (pola sama dengan master lain) ──
    is_integrated = fields.Boolean(string="Integrated", default=False, readonly=True, tracking=True)
    index_store = fields.Many2many('setting.config', string="Index Store", readonly=True)
    id_mc = fields.Char(string="ID MC", default=False, readonly=True)

    product_count = fields.Integer(string="Products", compute='_compute_product_count')

    _sql_constraints = [
        ('vit_artikel_code_unique', 'unique(vit_artikel_code)', 'Artikel Code sudah ada!'),
    ]

    def _compute_product_count(self):
        counts = dict(self.env['product.template']._read_group(
            [('vit_merchandise_category_id', 'in', self.ids)],
            ['vit_merchandise_category_id'], ['__count']))
        for rec in self:
            rec.product_count = counts.get(rec, 0)

    def action_view_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Products'),
            'res_model': 'product.template',
            'view_mode': 'tree,kanban,form',
            'domain': [('vit_merchandise_category_id', '=', self.id)],
            'context': {'default_vit_merchandise_category_id': self.id},
        }

    def write(self, vals):
        # Kalau data master berubah, tandai belum terintegrasi supaya ikut sync ulang ke semua store
        if any(f in vals for f in MERCHANDISE_CATEGORY_FIELDS + ['active']) \
                and 'is_integrated' not in vals and 'index_store' not in vals:
            vals = dict(vals, is_integrated=False, index_store=[(5, 0, 0)])
        return super().write(vals)
