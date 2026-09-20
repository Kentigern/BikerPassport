try:
    import pymysql
except ImportError:
    pass
else:
    # Krystal's shared cPanel hosting only offers MySQL/MariaDB, unlike
    # Railway's Postgres -- this shims Django's mysql backend (which expects
    # mysqlclient) onto the pure-Python PyMySQL, since shared hosting can't
    # compile mysqlclient's C extension. A no-op wherever DATABASE_URL points
    # at Postgres/SQLite instead (Railway, local dev).
    pymysql.install_as_MySQLdb()
