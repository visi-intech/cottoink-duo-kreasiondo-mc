import requests
from datetime import datetime, timedelta
import pytz
from odoo import models, fields, api, SUPERUSER_ID, _
from odoo.exceptions import UserError
from odoo.tools import float_compare
import random

# Nama operation type TS In (lowercase, spasi dinormalisasi)
TS_IN_TYPE_NAMES = {'ts in', 'transfer in'}

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_integrated = fields.Boolean(string="Integrated", default=False, readonly=True, tracking=True)
    is_closed = fields.Boolean(string="Closed", default=False, readonly=True, tracking=True)
    # copy=False: Return / Duplicate tidak ikut membawa Transaction ID dokumen asli
    # (kalau ikut, sync MC->SS menganggap dokumen sudah ada dan tidak membuat ulang).
    vit_trxid = fields.Char(string="Transaction ID", default=False, tracking=True, index=True, copy=False)
    target_location = fields.Char(string="Target Location")
    stock_type = fields.Many2one('master.type', string="Stock Type")

    # def write(self, vals):
    #     # Cek jika status sudah ready atau done dan mencoba mengubah field yang dibatasi
    #     restricted_states = ['assigned', 'done']  # ready = assigned, done = done
        
    #     for record in self:
    #         if record.state in restricted_states:
    #             # Field yang tidak boleh diubah ketika ready/done
    #             restricted_fields = ['target_location', 'stock_type', 'location_id', 'location_dest_id']
    #             for field in restricted_fields:
    #                 if field in vals:
    #                     raise UserError("Cannot modify field '%s' when transfer is in %s state." % (field, record.state))
                
    #             # Cek jika ada perubahan pada move lines (tambah/hapus item)
    #             if 'move_ids_without_package' in vals:
    #                 move_operations = vals.get('move_ids_without_package', [])
                    
    #                 for operation in move_operations:
    #                     # (0, 0, values) - CREATE new line
    #                     # (2, id, 0) - DELETE existing line
    #                     # (1, id, values) - UPDATE existing line (termasuk qty)
    #                     if operation[0] in (0, 2, 1):
    #                         if operation[0] == 0:
    #                             action = "add new items"
    #                         elif operation[0] == 2:
    #                             action = "delete items" 
    #                         else:
    #                             action = "modify items or quantities"
                            
    #                         raise UserError("Cannot %s when transfer is in %s state." % (action, record.state))
        
    #     return super(StockPicking, self).write(vals)

    def _is_ts_in(self):
        """True kalau operation type dokumen ini TS In / Transfer In.
        Nama dicek toleran (huruf besar/kecil & spasi), di bahasa user dan en_US."""
        self.ensure_one()
        picking_type = self.picking_type_id
        if not picking_type or picking_type.code != 'internal':
            return False
        names = {
            ' '.join((picking_type.name or '').split()).casefold(),
            ' '.join((picking_type.with_context(lang='en_US').name or '').split()).casefold(),
        }
        return bool(names & TS_IN_TYPE_NAMES)

    def _check_ts_in_quantity(self):
        """Blokir validate TS In jika ada Quantity < Demand."""
        for picking in self:
            if not picking._is_ts_in():
                continue

            kurang = []
            for move in picking.move_ids.filtered(lambda m: m.state != 'cancel'):
                rounding = move.product_uom.rounding
                if float_compare(move.quantity, move.product_uom_qty, precision_rounding=rounding) < 0:
                    kurang.append(_(
                        "- [%(code)s] %(name)s: Quantity %(qty)s dari Demand %(demand)s %(uom)s",
                        code=move.product_id.default_code or '-',
                        name=move.product_id.name,
                        qty=move.quantity,
                        demand=move.product_uom_qty,
                        uom=move.product_uom.name,
                    ))

            if kurang:
                raise UserError(_(
                    "Tidak dapat memvalidasi %(doc)s.\n\n"
                    "Quantity yang diterima kurang dari Demand untuk produk berikut:\n"
                    "%(lines)s\n\n"
                    "Pastikan seluruh Quantity sudah sesuai dengan Demand sebelum Validate.",
                    doc=picking.name,
                    lines="\n".join(kurang),
                ))

    def button_validate(self):
        for picking in self:
            # Check if the operation type is 'Internal Transfers'
            if picking.picking_type_id.code == 'internal':
                # Check if the source and destination locations are the same
                if picking.location_id.id == picking.location_dest_id.id:
                    raise UserError("Cannot validate this operation: Source and destination locations are the same.")

        # TS In: Quantity tidak boleh kurang dari Demand
        self._check_ts_in_quantity()

        # Call the super method
        res = super(StockPicking, self).button_validate()
        return res
    
    @api.model
    def create_stock_pickings(self):
        # Temukan ID untuk operation type TS Out
        operation_type_id = self.env['stock.picking.type'].search([('name', 'ilike', 'Goods Issue')], limit=1)
        if not operation_type_id:
            raise UserError('Operation Type TS Out tidak ditemukan.')
        
        product_codes = ['LBR00001', 'LBR00002', 'LBR00003', 'LBR00088', 'LBR00099', 'LBR00008', 'LBR00007', 'LBR00006', 'LBR00009', 'LBR00004']
        products = self.env['product.product'].search([('default_code', 'in', product_codes)])

        stock_pickings = []
        for i in range(500):
            # Mengatur move_lines untuk setiap `stock.picking`
            move_lines = []
            for j, product in enumerate(products):
                quantity = random.uniform(1, 10)
                move_lines.append((0, 0, {
                    'name': product.name,
                    'product_id': product.id,
                    'product_uom_qty': quantity,
                    'quantity': quantity,
                    'location_id': 4,
                    'location_dest_id': 8,
                }))

            stock_picking = {
                'picking_type_id': operation_type_id.id,
                'location_id': 4,
                'location_dest_id': 8,
                'move_ids_without_package': move_lines,
            }
            stock_pickings.append(stock_picking)
        
        self.env['stock.picking'].create(stock_pickings)

    def write_tsout(self):
        ts_out = self.env['stock.picking'].search([('picking_type_id.name', '=', 'TS In'), ('state', '=', 'assigned')])

        for res in ts_out:
            res.write({'is_integrated': True})

class StockMove(models.Model):
    _inherit = 'stock.move'

    vit_line_number_sap = fields.Integer(string='Line Number SAP')

    # def write(self, vals):
    #     # Cek jika picking terkait sudah ready atau done
    #     for record in self:
    #         if record.picking_id and record.picking_id.state in ['assigned', 'done']:
    #             raise UserError("Cannot modify stock moves when transfer is in %s state." % record.picking_id.state)
        
    #     return super(StockMove, self).write(vals)
    
    # def unlink(self):
    #     # Cek jika picking terkait sudah ready atau done
    #     for record in self:
    #         if record.picking_id and record.picking_id.state in ['assigned', 'done']:
    #             raise UserError("Cannot delete stock moves when transfer is in %s state." % record.picking_id.state)
        
    #     return super(StockMove, self).unlink()