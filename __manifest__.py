{
    'name': 'SIE 4 Export NG',
    'summary': 'Export Accounting Data to SIE 4 files',
    'version': '19.0.1.0.0',
    'author': 'Implefy AB',
    'license': 'LGPL-3',
    'category': 'Accounting/Localizations',
    'depends': ['account_reports', 'l10n_se'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/sie_export_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}
