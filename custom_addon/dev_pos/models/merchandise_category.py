from odoo import models, fields, api, _

# Semua field data master Merchandise Category (urutan sesuai spec SAP).
# Dipakai oleh sync MC->SS (data_integrator) dan API GET/POST.
MERCHANDISE_CATEGORY_FIELDS = [
    'u_varc', 'u_vszr', 'u_vmcc', 'u_vifc', 'u_vifn', 'u_vstc', 'u_vstn',
    'u_vscc', 'u_vscn', 'u_vctc', 'u_vctn', 'u_vsbc', 'u_vsbn', 'u_vbrc',
    'u_vbrn', 'u_vcrc', 'u_vcrn', 'u_vszc', 'u_vszn', 'u_vlbc', 'u_vlbn',
    'u_vwkc', 'u_vwkn', 'u_vqtc', 'u_vqtn', 'u_vctn_collection', 'u_vuby',
    'u_vefn',
]

# Field yang ditampilkan ulang (related, stored) di product.template / product.product.
# Upload By & Excel FileName hanya info upload, cukup di master.
MERCHANDISE_CATEGORY_PRODUCT_FIELDS = [
    f for f in MERCHANDISE_CATEGORY_FIELDS if f not in ('u_vuby', 'u_vefn')
]


class VitMerchandiseCategory(models.Model):
    _name = 'vit.merchandise.category'
    _description = 'Merchandise Category'
    _inherit = ['mail.thread']
    # PENTING: _rec_name = field unik di data_integrator ('u_varc').
    # data_integrator memetakan Many2one lewat display_name sumber == field unik target,
    # jadi display_name jangan dioverride.
    _rec_name = 'u_varc'
    _order = 'u_varc'

    u_varc = fields.Char(string="Artikel Code", size=50, required=True, index=True, tracking=True)
    u_vszr = fields.Char(string="Size Range", size=50)
    u_vmcc = fields.Char(string="MC Code", size=20)
    u_vifc = fields.Char(string="Flag Code", size=5)
    u_vifn = fields.Char(string="Flag Name", size=100)
    u_vstc = fields.Char(string="Style Code", size=5)
    u_vstn = fields.Char(string="Style Name", size=100)
    u_vscc = fields.Char(string="Sub Category Code", size=5)
    u_vscn = fields.Char(string="Sub Category Name", size=100)
    u_vctc = fields.Char(string="Category Code", size=5)
    u_vctn = fields.Char(string="Category Name", size=100)
    u_vsbc = fields.Char(string="Sub Brand Code", size=5)
    u_vsbn = fields.Char(string="Sub Brand Name", size=100)
    u_vbrc = fields.Char(string="Brand Code", size=5)
    u_vbrn = fields.Char(string="Brand Name", size=100)
    u_vcrc = fields.Char(string="Color Code", size=5)
    u_vcrn = fields.Char(string="Color Name", size=100)
    u_vszc = fields.Char(string="Size Code", size=5)
    u_vszn = fields.Char(string="Size Name", size=100)
    u_vlbc = fields.Char(string="Label Code", size=5)
    u_vlbn = fields.Char(string="Label Name", size=100)
    u_vwkc = fields.Char(string="Week Code", size=5)
    u_vwkn = fields.Char(string="Week Name", size=100)
    u_vqtc = fields.Char(string="Quarter Code", size=5)
    u_vqtn = fields.Char(string="Quarter Name", size=100)
    # Di spec, Collection Name juga bernama U_VCTN (bentrok dengan Category Name)
    u_vctn_collection = fields.Char(string="Collection Name", size=200)
    u_vuby = fields.Char(string="Upload By", size=200)
    u_vefn = fields.Char(string="Excel FileName", size=254)

    active = fields.Boolean(default=True)

    # ── Integrasi MC -> SS (pola sama dengan master lain) ──
    is_integrated = fields.Boolean(string="Integrated", default=False, readonly=True, tracking=True)
    index_store = fields.Many2many('setting.config', string="Index Store", readonly=True)
    id_mc = fields.Char(string="ID MC", default=False, readonly=True)

    _sql_constraints = [
        ('u_varc_unique', 'unique(u_varc)', 'Artikel Code (U_VARC) sudah ada!'),
    ]

    def write(self, vals):
        # Kalau data master berubah, tandai belum terintegrasi supaya ikut sync ulang ke semua store
        if any(f in vals for f in MERCHANDISE_CATEGORY_FIELDS + ['active']) \
                and 'is_integrated' not in vals and 'index_store' not in vals:
            vals = dict(vals, is_integrated=False, index_store=[(5, 0, 0)])
        return super().write(vals)
