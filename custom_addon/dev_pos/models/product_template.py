from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class VitMerchandiseCategoryMixin(models.AbstractModel):
    """Field Merchandise Category untuk product.template & product.product.
    Data disimpan di master vit.merchandise.category, produk cukup Many2one-nya;
    field vit_* di produk adalah related (stored, readonly) dari master."""
    _name = 'vit.merchandise.category.mixin'
    _description = 'Merchandise Category Mixin'

    vit_merchandise_category_id = fields.Many2one(
        'vit.merchandise.category', string="Merchandise Category",
        tracking=True, ondelete='restrict', index=True,
    )

    # ── Related dari vit.merchandise.category ──────────────
    vit_artikel_code = fields.Char(related='vit_merchandise_category_id.vit_artikel_code', string="Artikel Code", store=True)
    vit_size_range = fields.Char(related='vit_merchandise_category_id.vit_size_range', string="Size Range", store=True)
    vit_mc_code = fields.Char(related='vit_merchandise_category_id.vit_mc_code', string="MC Code", store=True)
    vit_flag_code = fields.Char(related='vit_merchandise_category_id.vit_flag_code', string="Flag Code", store=True)
    vit_flag = fields.Char(related='vit_merchandise_category_id.vit_flag', string="Flag Name", store=True)
    vit_style_code = fields.Char(related='vit_merchandise_category_id.vit_style_code', string="Style Code", store=True)
    vit_style = fields.Char(related='vit_merchandise_category_id.vit_style', string="Style Name", store=True)
    vit_sub_category_code = fields.Char(related='vit_merchandise_category_id.vit_sub_category_code', string="Sub Category Code", store=True)
    vit_sub_category = fields.Char(related='vit_merchandise_category_id.vit_sub_category', string="Sub Category Name", store=True)
    vit_category_code = fields.Char(related='vit_merchandise_category_id.vit_category_code', string="Category Code", store=True)
    vit_category = fields.Char(related='vit_merchandise_category_id.vit_category', string="Category Name", store=True)
    vit_sub_brand_code = fields.Char(related='vit_merchandise_category_id.vit_sub_brand_code', string="Sub Brand Code", store=True)
    vit_sub_brand = fields.Char(related='vit_merchandise_category_id.vit_sub_brand', string="Sub Brand Name", store=True)
    vit_brand_code = fields.Char(related='vit_merchandise_category_id.vit_brand_code', string="Brand Code", store=True)
    vit_brand = fields.Char(related='vit_merchandise_category_id.vit_brand', string="Brand Name", store=True)
    vit_color_code = fields.Char(related='vit_merchandise_category_id.vit_color_code', string="Color Code", store=True)
    vit_color = fields.Char(related='vit_merchandise_category_id.vit_color', string="Color Name", store=True)
    vit_size_code = fields.Char(related='vit_merchandise_category_id.vit_size_code', string="Size Code", store=True)
    vit_size = fields.Char(related='vit_merchandise_category_id.vit_size', string="Size Name", store=True)
    vit_label_code = fields.Char(related='vit_merchandise_category_id.vit_label_code', string="Label Code", store=True)
    vit_label = fields.Char(related='vit_merchandise_category_id.vit_label', string="Label Name", store=True)
    vit_week_code = fields.Char(related='vit_merchandise_category_id.vit_week_code', string="Week Code", store=True)
    vit_week = fields.Char(related='vit_merchandise_category_id.vit_week', string="Week Name", store=True)
    vit_quarter_code = fields.Char(related='vit_merchandise_category_id.vit_quarter_code', string="Quarter Code", store=True)
    vit_quarter = fields.Char(related='vit_merchandise_category_id.vit_quarter', string="Quarter Name", store=True)
    vit_collection = fields.Char(related='vit_merchandise_category_id.vit_collection', string="Collection Name", store=True)


class ProductTemplate(models.Model):
    _inherit = ['product.template', 'vit.merchandise.category.mixin']
    _name = 'product.template'

    is_integrated = fields.Boolean(string="Integrated", default=False)
    index_store = fields.Many2many('setting.config', string="Index Store")
    vit_sub_div = fields.Char(string="Sub Category")
    vit_item_kel = fields.Char(string="Kelompok")
    vit_item_type = fields.Char(string="Type")
    vit_is_discount = fields.Boolean(string="Discount")
    brand = fields.Char(string="Brand", tracking=True)

    # Many2one yang di-sync manual dari template ke semua variant
    SYNC_FIELDS = ['vit_merchandise_category_id']

    def _check_barcode_uniqueness(self):
        # Override untuk mematikan validasi barcode unik
        # Tidak akan pernah raise ValidationError lagi walaupun ada duplikat
        return True

    def write(self, vals):
        # Field-field yang readonly - tidak boleh diubah
        # readonly_fields = [
        #     'id_mc', 'vit_sub_div', 'vit_item_kel', 'vit_item_type', 'is_fixed_price', 'brand',
        #     'default_code', 'categ_id', 'standard_price', 'sale_ok', 'purchase_ok', 
        #     'taxes_id', 'detailed_type', 'invoice_policy', 'uom_id', 'uom_po_id'
        # ]
        
        # # Cek jika ada field readonly yang mencoba diubah
        # for field in readonly_fields:
        #     if field in vals:
        #         raise UserError(f"Cannot modify field '{self._fields[field].string}' as it is read-only.")
        
        # Simpan nilai lama SEBELUM super().write() dipanggil
        old_values = {}
        for record in self:
            old_values[record.id] = {
                'list_price': record.list_price,
                'product_tag_ids': record.product_tag_ids.mapped('name')
            }
        
        # Panggil super write
        result = super(ProductTemplate, self).write(vals)

        # Sync Many2one ke variants
        variant_vals = {f: vals[f] for f in self.SYNC_FIELDS if f in vals}
        if variant_vals:
            self.product_variant_ids.write(variant_vals)
        
        # Log ke chatter untuk list_price dan product_tag_ids
        for record in self:
            message_body = ""
            
            # Log untuk list_price
            if 'list_price' in vals:
                old_price = old_values[record.id]['list_price']
                new_price = vals['list_price']
                message_body += f"Sales Price updated: {old_price} → To: {new_price}\n"
            
            # Log untuk product_tag_ids
            if 'product_tag_ids' in vals:
                old_tags = old_values[record.id]['product_tag_ids']
                new_tags_operation = vals.get('product_tag_ids', [])
                
                # Process the operation to get new tags
                new_tags = []
                for operation in new_tags_operation:
                    if operation[0] == 6:  # REPLACE
                        new_tags = self.env['product.tag'].browse(operation[2]).mapped('name')
                    elif operation[0] == 4:  # ADD
                        tag = self.env['product.tag'].browse(operation[1])
                        new_tags = list(set(old_tags + [tag.name]))
                    elif operation[0] == 3:  # REMOVE
                        tag = self.env['product.tag'].browse(operation[1])
                        new_tags = [tag_name for tag_name in old_tags if tag_name != tag.name]
                    elif operation[0] == 5:  # CLEAR ALL
                        new_tags = []
                
                old_tags_str = ', '.join(old_tags) if old_tags else 'None'
                new_tags_str = ', '.join(new_tags) if new_tags else 'None'
                message_body += f"Product tags updated: Old Tags: {old_tags_str} → New Tags: {new_tags_str}"
            
            # Post message ke chatter jika ada perubahan
            if message_body:
                record.message_post(body=message_body)
        
        return result

    @api.model
    def create(self, vals):
        # Untuk create, log informasi ke chatter
        record = super(ProductTemplate, self).create(vals)

        # Sync Many2one ke variants
        variant_vals = {f: vals[f] for f in self.SYNC_FIELDS if f in vals}
        if variant_vals:
            record.product_variant_ids.write(variant_vals)
        
        message_body = "Product created with following information:\n"
        
        # Log list_price jika ada
        if 'list_price' in vals:
            message_body += f"- Sales Price: {vals['list_price']}\n"
        
        # Log product tags jika ada
        if 'product_tag_ids' in vals:
            tag_operations = vals.get('product_tag_ids', [])
            tag_names = []
            for operation in tag_operations:
                if operation[0] == 6:  # REPLACE
                    tags = self.env['product.tag'].browse(operation[2])
                    tag_names = tags.mapped('name')
                elif operation[0] == 4:  # ADD
                    tag = self.env['product.tag'].browse(operation[1])
                    tag_names.append(tag.name)
            
            if tag_names:
                message_body += f"- Tags: {', '.join(tag_names)}\n"
        
        record.message_post(body=message_body)
        
        return record


class ProductProductInherit(models.Model):
    _inherit = ['product.product', 'vit.merchandise.category.mixin']
    _name = 'product.product'

    vit_is_discount = fields.Boolean(string="Is Discount", default=False)

    @api.model_create_multi
    def create(self, vals_list):
        # Variant baru (mis. tambah attribute) ikut Merchandise Category dari template-nya
        for vals in vals_list:
            if 'vit_merchandise_category_id' not in vals and vals.get('product_tmpl_id'):
                tmpl = self.env['product.template'].browse(vals['product_tmpl_id'])
                if tmpl.vit_merchandise_category_id:
                    vals['vit_merchandise_category_id'] = tmpl.vit_merchandise_category_id.id
        return super().create(vals_list)

    def _check_barcode_uniqueness(self):
        # Override untuk mematikan validasi barcode unik
        # Tidak akan pernah raise ValidationError lagi walaupun ada duplikat
        return True