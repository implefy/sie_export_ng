import re
from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models, release
from odoo.exceptions import UserError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT

DATEFORMAT_SIE4 = '%Y%m%d'
DATEFORMAT_MAIN = DEFAULT_SERVER_DATE_FORMAT

# Chart template to KPTYP mapping
CHART_TEMPLATE_KPTYP = {
    'se': 'BAS2024',
}

# Account type to KTYP mapping
KTYP_ASSET = {
    'asset_receivable', 'asset_cash', 'asset_current',
    'asset_non_current', 'asset_prepayments', 'asset_fixed',
}
KTYP_LIABILITY = {
    'liability_payable', 'liability_credit_card', 'liability_current',
    'liability_non_current', 'equity', 'equity_unaffected', 'off_balance',
}
KTYP_EXPENSE = {'expense', 'expense_depreciation', 'expense_direct_cost'}


class GeneralLedgerCustomHandler(models.AbstractModel):
    _inherit = 'account.general.ledger.report.handler'

    def _custom_options_initializer(self, report, options, previous_options=None):
        super()._custom_options_initializer(report, options, previous_options)
        if self.env.company.account_fiscal_country_id.code == 'SE':
            options.setdefault('buttons', []).append({
                'name': _("SIE 4 Export NG"),
                'sequence': 50,
                'action': 'export_file',
                'action_param': 'export_sie4_file',
                'file_export_type': _("SIE"),
            })

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    @api.model
    def _get_sie4_dates(self, options, use_sie4_format=False):
        """Returns date strings for previous, current and next fiscal year."""
        result_strf = DATEFORMAT_SIE4 if use_sie4_format else DATEFORMAT_MAIN
        datetime_from = datetime.strptime(options['date']['date_from'], DATEFORMAT_MAIN)
        datetime_to = datetime.strptime(options['date']['date_to'], DATEFORMAT_MAIN)
        return {
            'prev_date_from': (datetime_from - relativedelta(years=1)).strftime(result_strf),
            'prev_date_to': (datetime_to - relativedelta(years=1)).strftime(result_strf),
            'curr_date_from': datetime_from.strftime(result_strf),
            'curr_date_to': datetime_to.strftime(result_strf),
            'next_date_from': (datetime_from + relativedelta(years=1)).strftime(result_strf),
            'next_date_to': (datetime_to + relativedelta(years=1)).strftime(result_strf),
        }

    @api.model
    def _get_sie4_ktyp(self, account_type):
        """Map Odoo account type to SIE4 KTYP code."""
        if account_type in KTYP_ASSET:
            return 'T'
        if account_type in KTYP_LIABILITY:
            return 'S'
        if account_type in KTYP_EXPENSE:
            return 'K'
        return 'I'

    @api.model
    def _get_sie4_options(self, report, date_from, date_to):
        """Create report options for a given date range."""
        return report.get_options({
            'date': {
                'date_from': date_from,
                'date_to': date_to,
                'mode': 'range',
                'filter': 'custom',
            },
            'export_mode': 'file',
        })

    @api.model
    def _get_sie4_orgnr(self, company):
        """Get organization number from company_registry or VAT."""
        if company.company_registry:
            return company.company_registry
        if company.vat:
            # Strip SE prefix and trailing suffix for Swedish VAT
            vat = company.vat
            if vat.upper().startswith('SE'):
                vat = vat[2:]
            # Remove trailing non-digit characters (e.g. "01" check digits after orgnr)
            # Swedish orgnr is 10 digits, VAT is orgnr + "01"
            if len(vat) == 12 and vat.endswith('01'):
                vat = vat[:10]
            # Format as NNNNNN-NNNN if 10 digits
            if len(vat) == 10 and vat.isdigit():
                return f'{vat[:6]}-{vat[6:]}'
            return vat
        return ''

    @api.model
    def _get_sie4_sru(self, account):
        """Extract SRU code from account tags matching 'SRU:\\d+'."""
        for tag in account.tag_ids:
            match = re.match(r'SRU[:\s]*(\d+)', tag.name or '')
            if match:
                return match.group(1)
        return None

    # -------------------------------------------------------------------------
    # Export sections
    # -------------------------------------------------------------------------

    @api.model
    def _export_sie4_identification(self, options):
        """Generate SIE4 identification/header section."""
        company = self.env['res.company'].browse(options['companies'][0]['id'])
        partner = company.partner_id
        dates = self._get_sie4_dates(options, use_sie4_format=True)

        # TAXAR: tax year = fiscal year end + 1 for calendar-year FY
        date_to = datetime.strptime(options['date']['date_to'], DATEFORMAT_MAIN)
        tax_year = date_to.year + 1

        # KPTYP mapping
        kptyp = CHART_TEMPLATE_KPTYP.get(company.chart_template, '')

        # ADRESS fields
        contact = partner.name or ''
        street = partner.street or ''
        zip_city = f'{partner.zip or ""} {partner.city or ""}'.strip()
        phone = partner.phone or ''

        lines = [
            '#FLAGGA 0',
            '#FORMAT PC8',
            '#SIETYP 4',
            f'#PROGRAM "Odoo SIE Export NG" {release.version}',
            f'#GEN {fields.Date.context_today(self).strftime(DATEFORMAT_SIE4)}',
            f'#FNAMN "{company.name}"',
            f'#ORGNR {self._get_sie4_orgnr(company)}',
            f'#ADRESS "{contact}" "{street}" "{zip_city}" "{phone}"',
            f'#RAR -1 {dates["prev_date_from"]} {dates["prev_date_to"]}',
            f'#RAR  0 {dates["curr_date_from"]} {dates["curr_date_to"]}',
            f'#TAXAR {tax_year}',
            f'#VALUTA {company.currency_id.name}',
        ]
        if kptyp:
            lines.append(f'#KPTYP {kptyp}')

        return lines

    @api.model
    def _export_sie4_chart_of_account(self, options):
        """Generate KONTO, KTYP and SRU lines for all accounts."""
        sie4_coa_lines = []
        company_id = options['companies'][0]['id']
        accounts = self.env['account.account'].with_company(company_id).search([])

        for account in accounts:
            sie4_coa_lines.append(f'#KONTO {account.code} "{account.name}"')
            sie4_coa_lines.append(f'#KTYP {account.code} {self._get_sie4_ktyp(account.account_type)}')
            sru = self._get_sie4_sru(account)
            if sru:
                sie4_coa_lines.append(f'#SRU {account.code} {sru}')

        return sie4_coa_lines

    @api.model
    def _get_sie4_initial_balances_values(self, report, options, filtered_accounts):
        """Get initial balance values using the report engine's _get_lines method."""
        def get_dict_values_from_report_line(line):
            return {
                'balance': line['columns'][colname_to_idx['balance']]['no_format'],
                'debit': line['columns'][colname_to_idx['debit']]['no_format'],
                'credit': line['columns'][colname_to_idx['credit']]['no_format'],
            }
        options = {
            **options,
            'unfold_all': True,
        }
        colname_to_idx = {col['expression_label']: idx for idx, col in enumerate(options.get('columns', []))}
        lines = report._get_lines(options)
        initial_balances = {}
        account_by_ids = {account.id: account for account in filtered_accounts}
        for line in lines:
            _model, res_id = report._get_model_info_from_id(line['id'])

            if isinstance(res_id, str) and 'balance_line' in res_id:
                account_id = report._get_res_id_from_line_id(line['id'], 'account.account')
                account = account_by_ids.get(account_id, False)
                if account:
                    initial_balances[account] = get_dict_values_from_report_line(line)

        return initial_balances

    @api.model
    def _export_sie4_bs_balance(self, options):
        """Generate IB/UB (opening/closing balance) lines for balance sheet accounts.

        Uses 3-period approach:
        - prev_year initial balance -> IB -1
        - curr_year initial balance -> UB -1 = IB 0
        - next_year initial balance -> UB 0
        """
        sie4_bs_balance_lines = []
        report = self.env['account.report'].browse(options['report_id'])
        dates = self._get_sie4_dates(options)
        company_id = options['companies'][0]['id']
        bs_accounts = self.env['account.account'].with_company(company_id).search_fetch(
            domain=[('include_initial_balance', '=', True)],
            field_names=['id'],
        )
        seen_bs_account_codes = set()
        prev_ib, prev_ub, curr_ib, curr_ub = {}, {}, {}, {}

        prev_year_options = self._get_sie4_options(report, dates['prev_date_from'], dates['prev_date_to'])
        next_year_options = self._get_sie4_options(report, dates['next_date_from'], dates['next_date_to'])
        report._init_currency_table(prev_year_options)
        report._init_currency_table(options)
        report._init_currency_table(next_year_options)
        prev_ib_values = self.with_company(company_id)._get_sie4_initial_balances_values(report, prev_year_options, bs_accounts)
        curr_ib_values = self.with_company(company_id)._get_sie4_initial_balances_values(report, options, bs_accounts)
        next_ib_values = self.with_company(company_id)._get_sie4_initial_balances_values(report, next_year_options, bs_accounts)

        for ib_values in (prev_ib_values, curr_ib_values, next_ib_values):
            for account, ib_item in ib_values.items():
                if ib_item != {}:
                    seen_bs_account_codes.add(account.code)
                    if ib_values is prev_ib_values:
                        prev_ib[account.code] = f'#IB -1 {account.code} {ib_item["balance"]}'
                    elif ib_values is curr_ib_values:
                        prev_ub[account.code] = f'#UB -1 {account.code} {ib_item["balance"]}'
                        curr_ib[account.code] = f'#IB  0 {account.code} {ib_item["balance"]}'
                    else:
                        curr_ub[account.code] = f'#UB  0 {account.code} {ib_item["balance"]}'

        default_ib_values = ('#IB -1', '#UB -1', '#IB  0', '#UB  0')
        for account_code in sorted(seen_bs_account_codes):
            for idx, period_ib in enumerate((prev_ib, prev_ub, curr_ib, curr_ub)):
                if account_code in period_ib:
                    sie4_bs_balance_lines.append(period_ib[account_code])
                else:
                    default_ib_value = default_ib_values[idx]
                    sie4_bs_balance_lines.append(f'{default_ib_value} {account_code} 0.0')

        return sie4_bs_balance_lines

    @api.model
    def _export_sie4_pl_balance(self, options):
        """Generate RES (result) lines for P&L accounts."""
        sie4_pl_balance_lines = []
        dates = self._get_sie4_dates(options)
        company_id = options['companies'][0]['id']

        common_domain = [
            ('account_id.include_initial_balance', '=', False),
            ('display_type', 'not in', ('line_section', 'line_subsection', 'line_note')),
        ]
        prev_year_domain = common_domain + [
            ('date', '>=', dates['prev_date_from']),
            ('date', '<=', dates['prev_date_to']),
        ]
        curr_year_domain = common_domain + [
            ('date', '>=', dates['curr_date_from']),
            ('date', '<=', dates['curr_date_to']),
        ]

        prev_account_sum_group = self.env['account.move.line'].with_company(company_id)._read_group(
            prev_year_domain, ['account_id'], ['balance:sum'])
        curr_account_sum_group = self.env['account.move.line'].with_company(company_id)._read_group(
            curr_year_domain, ['account_id'], ['balance:sum'])
        prev_code_sum_map = {account.code: str(account_sum) for account, account_sum in prev_account_sum_group}
        curr_code_sum_map = {account.code: str(account_sum) for account, account_sum in curr_account_sum_group}
        seen_account_code = set(prev_code_sum_map.keys()).union(curr_code_sum_map.keys())

        for account_code in sorted(seen_account_code):
            sie4_pl_balance_lines.extend((
                f'#RES -1 {account_code} {prev_code_sum_map.get(account_code, "0.0")}',
                f'#RES  0 {account_code} {curr_code_sum_map.get(account_code, "0.0")}',
            ))

        return sie4_pl_balance_lines

    @api.model
    def _export_sie4_verification(self, options):
        """Generate VER/TRANS lines for all posted moves in the fiscal year.

        Uses journal code as series and sequence_number as verification number.
        Includes registration date (create_date).
        """
        sie4_verification_lines = []
        dates = self._get_sie4_dates(options)
        company_id = options['companies'][0]['id']
        unsupported_display_type = {'line_note', 'line_section', 'line_subsection'}

        moves = self.env['account.move'].with_company(company_id).search([
            ('state', '=', 'posted'),
            ('date', '>=', dates['curr_date_from']),
            ('date', '<=', dates['curr_date_to']),
        ], order='journal_id, name')

        for move in moves:
            transactions = []
            for line in move.line_ids:
                if line.display_type not in unsupported_display_type:
                    transactions.append(f'    #TRANS {line.account_id.code} {{}} {line.balance}')

            series = move.journal_id.code
            ver_date = move.date.strftime(DATEFORMAT_SIE4)
            reg_date = move.create_date.strftime(DATEFORMAT_SIE4) if move.create_date else ''

            ver_line = f'#VER {series} "{move.name}" {ver_date} "{move.name}"'
            if reg_date:
                ver_line += f' {reg_date}'

            sie4_verification_lines.extend((
                ver_line,
                '{', *transactions, '}',
            ))

        return sie4_verification_lines

    # -------------------------------------------------------------------------
    # Main entry point
    # -------------------------------------------------------------------------

    def export_sie4_file(self, options):
        """Export SIE 4 file from General Ledger report."""
        if options['date']['period_type'] != 'fiscalyear':
            raise UserError(_("You must set the period type to fiscal year in order to export a SIE 4 file."))

        if len(options['companies']) > 1:
            selected_companies = self.env['res.company'].search_fetch(
                domain=[('id', 'in', [c['id'] for c in options['companies']])],
                field_names=['chart_template'],
            )
            if len(set(selected_companies.mapped('chart_template'))) >= 2:
                raise UserError(_("You can't export multiple companies with different chart templates."))
            options['companies'] = [
                c for c in options['companies'] if c['id'] == self.env.company.id
            ]

        content_lines = [
            *self._export_sie4_identification(options),
            *self._export_sie4_chart_of_account(options),
            *self._export_sie4_bs_balance(options),
            *self._export_sie4_pl_balance(options),
            *self._export_sie4_verification(options),
            '',  # ensure file ends with newline
        ]

        return {
            'file_name': f'sie4_export_{fields.Date.context_today(self).strftime(DATEFORMAT_SIE4)}.se',
            'file_content': '\n'.join(content_lines).encode('437'),
            'file_type': 'txt',
        }
