"""Register every blueprint (group of routes) with the app."""


def register_blueprints(app):
    from .admin import bp as admin_bp
    from .approvals import bp as approvals_bp
    from .auth import bp as auth_bp
    from .dashboard import bp as dashboard_bp
    from .network import bp as network_bp
    from .org import bp as org_bp
    from .pages import bp as pages_bp
    from .qr import bp as qr_bp
    from .reports import bp as reports_bp
    from .sync import bp as sync_bp
    from .visitors import bp as visitors_bp

    for bp in (pages_bp, auth_bp, visitors_bp, qr_bp, approvals_bp, org_bp, admin_bp,
               dashboard_bp, network_bp, sync_bp, reports_bp):
        app.register_blueprint(bp)
