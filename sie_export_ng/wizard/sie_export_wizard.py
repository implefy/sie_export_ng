from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SieExportWizard(models.TransientModel):
    _name = 'sie.export.wizard'
    _description = 'SIE 4 Export Wizard'

    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To', required=True)
    file_data = fields.Binary(string='File', readonly=True)
    file_name = fields.Char(string='File Name', readonly=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise UserError(_("'Date From' must be earlier than 'Date To'."))

    def action_export(self):
        self.ensure_one()
        report = self.env.ref('account_reports.general_ledger_report')
        handler = self.env[report.custom_handler_model_name]

        # Build options matching what the report engine expects
        options = report.get_options({
            'date': {
                'date_from': fields.Date.to_string(self.date_from),
                'date_to': fields.Date.to_string(self.date_to),
                'mode': 'range',
                'filter': 'custom',
            },
        })

        # The report engine sets period_type based on fiscal year detection.
        # For the wizard we force it so the export works with any date range.
        options['date']['period_type'] = 'fiscalyear'

        result = handler.export_sie4_file(options)

        import base64
        self.write({
            'file_data': base64.b64encode(result['file_content']),
            'file_name': result['file_name'],
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model=sie.export.wizard&id={self.id}'
                   f'&field=file_data&filename_field=file_name&download=true',
            'target': 'self',
        }
