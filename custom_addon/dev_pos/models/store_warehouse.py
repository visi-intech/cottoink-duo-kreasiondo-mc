import requests
from datetime import datetime, timedelta
import pytz
from odoo import models, fields, api, SUPERUSER_ID
from odoo.exceptions import UserError

class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    # Standar Odoo size=5 -> kode SAP (mis. CANUGRAH, STPKWSBY) terpotong & bentrok.
    code = fields.Char(size=20)

    location_transit = fields.Many2one('stock.location', string="Transit Location")
    is_send_to_store = fields.Boolean(string="Is Send to Store", default=False)