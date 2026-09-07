"""Run only with KWIP_UAT=1 DJANGO_SETTINGS_MODULE=uat.settings."""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'uat.settings')
import django
django.setup()
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from plane.access.models import Identity, Workspace
from plane.catalog.services import register_dataset, register_source, ingest_batch
from plane.commerce.models import BillingAccount
assert settings.ROOT_URLCONF == 'uat.urls'
for actor in ('free', 'pro', 'operator'):
    identity, _ = Identity.objects.get_or_create(subject='user_uat_' + actor, defaults={'is_operator': actor=='operator'})
    workspace, _ = Workspace.objects.get_or_create(owner=identity, defaults={'name': 'Synthetic ' + actor})
    if actor == 'pro':
        BillingAccount.objects.update_or_create(workspace=workspace, defaults={'status':'active','period_start':timezone.now()-timedelta(days=1),'period_end':timezone.now()+timedelta(days=29)})
manifest={'slug':'synthetic-jobs','title':'Synthetic job postings','description':'Local UAT fixture. Invented companies and postings; not collected from any external source.','category':'Jobs','schema_version':1,'fields':{'company':{'type':'string','required':True},'role':{'type':'string','required':True},'salary_usd':{'type':'integer'},'remote':{'type':'boolean'}},'credits_per_record':2}
dataset=register_dataset(manifest)
source=register_source(dataset,{'slug':'synthetic','name':'Synthetic fixture','url':'https://example.com/uat','attribution':'Invented solely for software tests.','license_url':'https://example.com/uat-license','rights_status':'approved','schema_version':1})
items=[{'external_id':str(i),'payload':{'company':'Example Company '+str(i%5),'role':'Software engineer' if i%2 else 'Data analyst','salary_usd':100000+i*1000,'remote':bool(i%2)},'observed_at':'2026-09-07T12:00:00Z'} for i in range(63)]
ingest_batch(source,items,'synthetic-fixture-v1')
register_dataset(manifest | {'status':'published'})
print('Synthetic UAT accounts and 63 invented records ready in isolated local PostgreSQL UAT database.')
