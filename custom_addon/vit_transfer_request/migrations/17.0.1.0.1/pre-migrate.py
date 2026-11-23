# -*- coding: utf-8 -*-
"""Status 'To Approve' dan 'Approved' dihapus dari Transfer Request.

Dokumen lama dipindah supaya tidak punya state yang sudah tidak ada di selection:
  - approved   -> in_progress  (sudah disetujui, siap Rilis Transfer Out)
  - to_approve -> draft        (belum pernah disetujui; konservatif, tidak ikut tertarik
                                integrasi SAP sampai user klik Submit lagi)
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("UPDATE transfer_request SET state = 'in_progress' WHERE state = 'approved'")
    _logger.info("vit_transfer_request: %s Transfer Request approved -> in_progress", cr.rowcount)
    cr.execute("UPDATE transfer_request SET state = 'draft' WHERE state = 'to_approve'")
    _logger.info("vit_transfer_request: %s Transfer Request to_approve -> draft", cr.rowcount)
