import logging
import re

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

TS_IN_GROUP = 'vit_transfer_request.group_ts_in_creator'
TS_OUT_NAME = 'TS Out'
TS_IN_NAME = 'TS In'


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    vit_transfer_request_id = fields.Many2one('transfer.request', string='Transfer Request',
                                               readonly=True, index=True, copy=False,
                                               help='Transfer Request (MD) yang menjadi dasar Transfer Out ini.')
    vit_transfer_type_id = fields.Many2one('transfer.type', string='Transfer Type',
                                            help='Jenis transaksi untuk Transfer Out.')
    transfer_out_id = fields.Many2one('stock.picking', string='TS Out Reference',
                                       domain="[('picking_type_id.name', '=', 'TS Out')]",
                                       index=True, copy=False,
                                       help='Dokumen TS Out yang menjadi dasar TS In ini. '
                                            'Wajib diisi pada dokumen TS In.')
    vit_warehouse_id = fields.Many2one('stock.warehouse', string='Source Warehouse',
                                        index=True, copy=False,
                                        help='Gudang asal. Terisi otomatis kalau dokumen dibuat dari '
                                             'Transfer Request / TS Out. Pada TS Out, memilih gudang ini '
                                             'mengisi Source Location dengan stock location gudang.')
    vit_warehouse_dest_id = fields.Many2one('stock.warehouse', string='Destination Warehouse',
                                             index=True, copy=False,
                                             help='Gudang tujuan akhir. Pada TS Out dipakai untuk menentukan '
                                                  'lokasi tujuan TS In (stock gudang ini). Terisi otomatis '
                                                  'kalau TS Out dibuat dari Transfer Request.')
    vit_is_ts_in = fields.Boolean(string='Is TS In', compute='_compute_vit_is_ts_in',
                                   help='Technical: dokumen ini memakai operation type TS In.')
    vit_is_ts_out = fields.Boolean(string='Is TS Out', compute='_compute_vit_is_ts_out',
                                    help='Technical: dokumen ini memakai operation type TS Out.')
    ts_in_ids = fields.One2many('stock.picking', 'transfer_out_id', string='TS In')
    ts_in_count = fields.Integer(string='TS In', compute='_compute_ts_in_count')

    @staticmethod
    def _vit_normalize_type_name(name):
        """Samakan nama operation type: abaikan huruf besar/kecil dan spasi
        berlebih/tersembunyi (termasuk non-breaking space)."""
        return ' '.join((name or '').split()).casefold()

    def _vit_type_matches(self, picking_type, target):
        """True kalau nama operation type == target (toleran: huruf besar/kecil, spasi,
        dan dicek di bahasa user + en_US karena name translatable)."""
        wanted = self._vit_normalize_type_name(target)
        names = {
            self._vit_normalize_type_name(picking_type.name),
            self._vit_normalize_type_name(picking_type.with_context(lang='en_US').name),
        }
        return wanted in names

    @api.depends('picking_type_id.name')
    def _compute_vit_is_ts_in(self):
        for picking in self:
            picking.vit_is_ts_in = self._vit_type_matches(picking.picking_type_id, TS_IN_NAME)

    @api.depends('picking_type_id.name')
    def _compute_vit_is_ts_out(self):
        for picking in self:
            picking.vit_is_ts_out = self._vit_type_matches(picking.picking_type_id, TS_OUT_NAME)

    # ------------------------------------------------------------------
    # Penomoran TS Out / TS In: TSOT/<kode WH>/<tahun>/00001 dan TSIN/<kode WH>/<tahun>/00001.
    # Di MC kode WH diambil dari Source Warehouse. Dokumen hasil sync dari Store sudah membawa
    # nomornya sendiri (name terisi), jadi tidak diberi nomor baru di sini.
    # ------------------------------------------------------------------
    @api.model
    def _vit_numbering_warehouse(self, vals, picking_type):
        warehouse = self.env['stock.warehouse']
        if vals.get('vit_warehouse_id'):
            warehouse = warehouse.browse(vals['vit_warehouse_id'])
        if not warehouse and vals.get('location_id'):
            warehouse = self.env['stock.location'].browse(vals['location_id']).warehouse_id
        return warehouse or picking_type.warehouse_id

    @api.model
    def _vit_next_ts_name(self, prefix, code, batch_counter):
        """Nomor berikutnya = nomor terbesar yang sudah dipakai dokumen dengan prefix yang sama + 1
        (termasuk dokumen hasil sync). Advisory lock menyerialkan pembuatan nomor supaya dua user
        tidak mendapat nomor yang sama."""
        year = fields.Date.context_today(self).year
        base = '%s/%s/%s/' % (prefix, code, year)
        if base not in batch_counter:
            self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (base,))
            like = base.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            pattern = '^%s[0-9]+$' % re.escape(base)
            self.env.cr.execute(
                "SELECT max(substring(name from '([0-9]+)$')::bigint) FROM stock_picking "
                "WHERE name LIKE %s AND name ~ %s", (like, pattern))
            batch_counter[base] = self.env.cr.fetchone()[0] or 0
        batch_counter[base] += 1
        return '%s%05d' % (base, batch_counter[base])

    @api.model_create_multi
    def create(self, vals_list):
        batch_counter = {}
        for vals in vals_list:
            if vals.get('name') not in (None, False, '', '/'):
                continue
            type_id = vals.get('picking_type_id') or self.default_get(['picking_type_id']).get('picking_type_id')
            if not type_id:
                continue
            picking_type = self.env['stock.picking.type'].browse(type_id)
            if self._vit_type_matches(picking_type, TS_OUT_NAME):
                prefix = 'TSOT'
            elif self._vit_type_matches(picking_type, TS_IN_NAME):
                prefix = 'TSIN'
            else:
                continue
            code = (self._vit_numbering_warehouse(vals, picking_type).code or '').strip()
            if code:  # tanpa kode WH: biarkan penomoran bawaan Odoo
                vals['name'] = self._vit_next_ts_name(prefix, code, batch_counter)
        return super().create(vals_list)

    @api.model
    def default_get(self, fields_list):
        """Create New dari menu TS Out / TS In: isi Operation Type otomatis, supaya
        vit_is_ts_out / vit_is_ts_in sudah benar sejak form baru dan layout TS Out/TS In
        langsung tampil. Penandanya context `vit_default_ts_kind` ('ts_out' / 'ts_in');
        tanpa penanda itu (menu lain) perilaku bawaan Odoo tidak berubah."""
        res = super().default_get(fields_list)
        kind = self.env.context.get('vit_default_ts_kind')
        if kind in ('ts_out', 'ts_in') and 'picking_type_id' in fields_list and not res.get('picking_type_id'):
            target = TS_OUT_NAME if kind == 'ts_out' else TS_IN_NAME
            types = self.env['stock.picking.type'].search(
                [('company_id', '=', self.env.company.id)]).filtered(
                lambda t: self._vit_type_matches(t, target))
            if types:
                res['picking_type_id'] = types[0].id
        return res

    @api.onchange('vit_warehouse_id')
    def _onchange_vit_warehouse_id(self):
        """Sama seperti Transfer Request: Source Location TS Out diisi stock location gudang asal."""
        if self.vit_warehouse_id and self.vit_is_ts_out:
            self.location_id = self.vit_warehouse_id.lot_stock_id

    @api.onchange('vit_warehouse_dest_id')
    def _onchange_vit_warehouse_dest_id(self):
        """Sama seperti Transfer Request: Destination Location TS Out diisi transit
        location gudang tujuan (kalau ada), kalau tidak stock location gudang itu."""
        if self.vit_warehouse_dest_id and self.vit_is_ts_out:
            warehouse = self.vit_warehouse_dest_id
            self.location_dest_id = warehouse.location_transit or warehouse.lot_stock_id

    @api.depends('ts_in_ids.state')
    def _compute_ts_in_count(self):
        for picking in self:
            picking.ts_in_count = len(picking.ts_in_ids.filtered(lambda p: p.state != 'cancel'))

    # ------------------------------------------------------------------
    # TS Out -> TS In
    # ------------------------------------------------------------------
    def _check_ts_in_access(self):
        if not self.env.user.has_group(TS_IN_GROUP):
            raise AccessError(_("Kamu tidak punya hak akses untuk membuat / melihat dokumen TS In."))

    def _get_ts_in_picking_type(self):
        """Operation type TS In; utamakan milik warehouse tujuan TS Out."""
        self.ensure_one()
        # filter di Python (bukan ilike) supaya nama dengan spasi tersembunyi tetap ketemu;
        # jumlah operation type kecil, jadi aman.
        types = self.env['stock.picking.type'].search([]).filtered(
            lambda t: self._vit_type_matches(t, TS_IN_NAME))
        if not types:
            raise UserError(_("Operation Type '%s' tidak ditemukan.", TS_IN_NAME))
        dest_warehouse = self.vit_warehouse_dest_id or self.location_dest_id.warehouse_id
        preferred = types.filtered(lambda t: t.warehouse_id == dest_warehouse) if dest_warehouse else types.browse()
        return (preferred or types)[:1]

    def _prepare_ts_in_values(self, picking_type, move_vals):
        self.ensure_one()
        # Tujuan TS In: stock location Destination Warehouse yang diisi di TS Out.
        # Fallback (TS Out lama / dari API yang belum punya gudang tujuan): setting operation type TS In.
        if self.vit_warehouse_dest_id:
            dest_location = self.vit_warehouse_dest_id.lot_stock_id
            if not dest_location:
                raise UserError(_("Gudang %s belum punya Location Stock.", self.vit_warehouse_dest_id.display_name))
        else:
            dest_location = picking_type.default_location_dest_id or picking_type.warehouse_id.lot_stock_id
        if not dest_location:
            raise UserError(_("Isi Destination Warehouse di TS Out, atau set Default Destination "
                              "Location pada Operation Type %s.", picking_type.display_name))
        if dest_location == self.location_dest_id:
            raise UserError(_("Lokasi tujuan TS In (%s) sama dengan lokasi asalnya (Destination Location "
                              "TS Out). Perpindahan antar gudang harus lewat lokasi transit: isi Transit "
                              "Location pada gudang tujuan, lalu pakai sebagai Destination Location TS Out.",
                              dest_location.display_name))
        for _cmd, _id, vals in move_vals:
            vals['location_dest_id'] = dest_location.id
        return {
            'picking_type_id': picking_type.id,
            'location_id': self.location_dest_id.id,
            'location_dest_id': dest_location.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'vit_transfer_type_id': self.vit_transfer_type_id.id,
            'transfer_out_id': self.id,
            'vit_warehouse_id': self.vit_warehouse_id.id,
            'vit_warehouse_dest_id': self.vit_warehouse_dest_id.id,
            'move_ids_without_package': move_vals,
        }

    def _create_ts_in(self):
        """Buat TS In dari TS Out yang sudah Done, sesuai qty yang BENAR-BENAR dikirim
        (move.quantity). Kalau TS Out divalidasi sebagian, backorder-nya adalah picking
        terpisah dan akan membuat TS In sendiri saat divalidasi."""
        self.ensure_one()
        if not self.vit_is_ts_out or self.state != 'done':
            return self.browse()
        # idempotent: satu TS Out cuma dibuatkan satu TS In
        if self.ts_in_ids.filtered(lambda p: p.state != 'cancel'):
            return self.browse()

        move_vals = []
        for line_number, move in enumerate(self.move_ids.filtered(lambda m: m.state == 'done'), start=1):
            if float_compare(move.quantity, 0.0, precision_rounding=move.product_uom.rounding) <= 0:
                continue
            move_vals.append((0, 0, {
                'name': move.product_id.display_name,
                'product_id': move.product_id.id,
                'product_uom': move.product_uom.id,
                'product_uom_qty': move.quantity,
                'location_id': self.location_dest_id.id,
                'location_dest_id': self.location_dest_id.id,  # ditimpa di _prepare_ts_in_values
                'vit_line_number_sap': line_number,
                'vit_ts_out_move_id': move.id,
            }))
        if not move_vals:
            return self.browse()

        picking_type = self._get_ts_in_picking_type()
        ts_in = self.env['stock.picking'].create(self._prepare_ts_in_values(picking_type, move_vals))
        ts_in._set_ts_in_ready()
        return ts_in

    def _set_ts_in_ready(self):
        """TS In langsung Ready (assigned), bukan Draft: confirm lalu reserve stok di lokasi
        asal (transit) yang barusan diisi oleh TS Out. Kalau gagal / stok belum cukup,
        TS In tetap terbentuk (status mengikuti Odoo) dan alasannya dicatat di chatter."""
        for picking in self:
            try:
                with self.env.cr.savepoint():
                    picking.action_confirm()
                    picking.action_assign()
            except Exception as exc:  # noqa: BLE001 - dicatat di log + chatter, bukan ditelan
                _logger.exception("Gagal set Ready TS In %s", picking.name)
                picking.message_post(body=_(
                    "TS In gagal di-set Ready otomatis: %s. Klik Confirm / Check Availability manual.",
                    str(exc)))
                continue
            if picking.state != 'assigned':
                picking.message_post(body=_(
                    "TS In belum bisa langsung Ready (status: %s). Cek ketersediaan stok di %s.",
                    dict(picking._fields['state'].selection).get(picking.state, picking.state),
                    picking.location_id.display_name))

    def _action_done(self):
        """Hook di picking (bukan button_validate) supaya TS In tetap terbentuk lewat
        wizard backorder / immediate transfer maupun validasi dari kode."""
        res = super()._action_done()
        for picking in self.filtered(lambda p: p.state == 'done' and p.vit_is_ts_out):
            try:
                # savepoint: kegagalan bikin TS In tidak boleh membatalkan validasi TS Out
                with self.env.cr.savepoint():
                    ts_in = picking._create_ts_in()
            except Exception as exc:  # noqa: BLE001 - dicatat di log + chatter, bukan ditelan
                _logger.exception("Gagal membuat TS In otomatis dari %s", picking.name)
                picking.message_post(body=_(
                    "TS In otomatis GAGAL dibuat: %s. Cek Operation Type TS In "
                    "(Default Destination Location) lalu buat TS In secara manual.", str(exc)))
                continue
            if ts_in:
                picking.message_post(body=_("TS In %s dibuat otomatis setelah TS Out ini Done.", ts_in.name))
        return res

    def _vit_check_ts_in_equals_ts_out(self):
        """Block TS In: qty TS In harus sama dengan qty TS Out (tidak boleh kurang, tidak boleh lebih).
        Hanya untuk move TS In yang terhubung ke move TS Out (TS In yang dibuat dari TS Out)."""
        for picking in self.filtered('vit_is_ts_in'):
            problems = []
            for move in picking.move_ids.filtered(lambda m: m.state != 'cancel' and m.vit_ts_out_move_id):
                out = move.vit_ts_out_move_id
                out_qty = out.product_uom._compute_quantity(out.quantity, move.product_uom)
                rounding = move.product_uom.rounding
                if (float_compare(move.quantity, out_qty, precision_rounding=rounding) != 0
                        or float_compare(move.product_uom_qty, out_qty, precision_rounding=rounding) != 0):
                    problems.append(_("- [%(code)s] %(name)s: TS In %(qty)s (demand %(demand)s), TS Out %(out)s",
                                      code=move.product_id.default_code or '-', name=move.product_id.name,
                                      qty=move.quantity, demand=move.product_uom_qty, out=out_qty))
            if problems:
                raise UserError(_("Tidak dapat memvalidasi %(doc)s.\n\nQty TS In harus sama dengan qty TS Out:\n%(lines)s",
                                  doc=picking.name, lines='\n'.join(problems)))

    def button_validate(self):
        self._vit_check_ts_in_equals_ts_out()
        # constraint di stock.move bisa tidak terpicu kalau qty berubah lewat move line
        # (quantity adalah field compute), jadi dicek ulang tepat sebelum validasi.
        self.move_ids._check_vit_not_over_transfer_request()
        self.move_ids._check_vit_ts_in_not_over_ts_out()
        return super().button_validate()

    def action_view_ts_in(self):
        self.ensure_one()
        self._check_ts_in_access()
        return {
            'type': 'ir.actions.act_window',
            'name': _('TS In'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('transfer_out_id', '=', self.id)],
            'context': {'create': False},
        }


class StockMove(models.Model):
    _inherit = 'stock.move'

    vit_transfer_request_line_id = fields.Many2one('transfer.request.line', string='Transfer Request Line',
                                                    readonly=True, index=True, copy=False)
    vit_ts_out_move_id = fields.Many2one('stock.move', string='TS Out Move',
                                          readonly=True, index=True, copy=False,
                                          help='Move pada TS Out yang menjadi dasar move TS In ini.')

    def _action_done(self, *args, **kwargs):
        """Hook di move, bukan di button_validate, supaya progress request tetap benar
        walaupun Transfer Out-nya lewat wizard backorder / immediate transfer (IT-02)."""
        moves_done = super(StockMove, self)._action_done(*args, **kwargs)
        requests = moves_done.vit_transfer_request_line_id.request_id
        if requests:
            requests._update_fulfilment_state()
        return moves_done

    @api.constrains('product_uom_qty', 'quantity', 'state', 'vit_transfer_request_line_id')
    def _check_vit_not_over_transfer_request(self):
        """TS Out boleh kurang dari Transfer Request, tetapi tidak boleh lebih."""
        for line in self.filtered('vit_transfer_request_line_id').vit_transfer_request_line_id:
            moves = line.move_ids.filtered(lambda m: m.state != 'cancel')
            demand = sum(m.product_uom._compute_quantity(m.product_uom_qty, line.product_uom_id) for m in moves)
            qty = sum(m.product_uom._compute_quantity(m.quantity, line.product_uom_id) for m in moves)
            if float_compare(max(demand, qty), line.product_uom_qty,
                             precision_rounding=line.product_uom_id.rounding) > 0:
                raise ValidationError(_(
                    "Qty Transfer Out untuk [%(code)s] %(name)s (%(qty)s) melebihi qty Transfer Request %(doc)s (%(req)s).",
                    code=line.product_id.default_code or '-', name=line.product_id.name,
                    qty=max(demand, qty), doc=line.request_id.doc_num, req=line.product_uom_qty))

    @api.constrains('product_uom_qty', 'quantity', 'vit_ts_out_move_id')
    def _check_vit_ts_in_not_over_ts_out(self):
        """Qty TS In tidak boleh melebihi qty TS Out yang menjadi dasarnya."""
        for out in self.filtered('vit_ts_out_move_id').vit_ts_out_move_id:
            ins = self.env['stock.move'].search([('vit_ts_out_move_id', '=', out.id), ('state', '!=', 'cancel')])
            demand = sum(m.product_uom._compute_quantity(m.product_uom_qty, out.product_uom) for m in ins)
            qty = sum(m.product_uom._compute_quantity(m.quantity, out.product_uom) for m in ins)
            if float_compare(max(demand, qty), out.quantity, precision_rounding=out.product_uom.rounding) > 0:
                raise ValidationError(_(
                    "Qty TS In untuk [%(code)s] %(name)s (%(qty)s) melebihi qty TS Out %(doc)s (%(out)s).",
                    code=out.product_id.default_code or '-', name=out.product_id.name,
                    qty=max(demand, qty), doc=out.picking_id.name, out=out.quantity))
