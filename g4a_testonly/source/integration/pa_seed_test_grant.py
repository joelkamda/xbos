"""Seed only synthetic TEST-scope entitlement on isolated disposable PG17."""
from rehearsal_v3.seed import connect
from datetime import datetime,timezone,timedelta
from rehearsal_v3.v24_pa_test_publish_grant import GRADE,PERMISSION
now=datetime.now(timezone.utc)
with connect() as db:
  with db.cursor() as c:
    c.execute("""INSERT INTO v24_pa_test_publish_policy
                   (tenant_id,branch_id,enabled,minimum_issuer_epoch)
                   VALUES(920002,1,TRUE,7)""")
    c.execute("""INSERT INTO v24_pa_test_publish_grants
                   (tenant_id,branch_id,actor_ref,permission,issuer_epoch,valid_from,valid_until,grade)
                   VALUES(920002,1,'reviewer',%s,7,%s,%s,%s)""",
              (PERMISSION,now-timedelta(hours=1),now+timedelta(hours=1),GRADE))
  db.commit()
print("PA_SYNTHETIC_TEST_GRANT_SEEDED_NOT_PC5=PASS")
