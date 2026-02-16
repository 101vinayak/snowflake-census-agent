import snowflake.connector

conn = snowflake.connector.connect(
    user="VINAYAKD",
    password="uLq4FMfda6rZtKd",
    account="HMFNMOY-SWC80553",  # <-- change to your Account Identifier from Snowflake "About"
    authenticator="snowflake",   # <-- forces username/password auth (no SAML)
    warehouse="WH_AGENT",
    database="APP_DB",
    schema="APP_SCHEMA",
    role="SYSADMIN",
)

cur = conn.cursor()
cur.execute("SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE()")
print(cur.fetchone())

cur.execute("SELECT * FROM APP_DB.APP_SCHEMA.V_COMMUTE_STATE_NAMED ORDER BY AVG_COMMUTE_MINUTES DESC LIMIT 5")
for row in cur.fetchall():
    print(row)

cur.close()
conn.close()

