from django.http import HttpResponse, JsonResponse
from plane.access.http import body_json, endpoint
from plane.access.errors import Problem
from .models import ExportJob
from .services import create_export, download, job_json, owned_job


@endpoint(('GET', 'POST'))
def jobs(request, principal):
    if request.method == 'GET':
        principal.require('exports:read')
        principal.require('datasets:read')
        from plane.commerce.services import account_for, pro_active
        if not pro_active(account_for(principal.workspace)):
            raise Problem('pro_required', 'Exports require an active Pro plan.', 403)
        jobs = ExportJob.objects.filter(workspace=principal.workspace).select_related('dataset').order_by('-created_at')[:20]
        # Apply dataset restrictions and current authority to each job before metadata.
        result = []
        for job in jobs:
            try:
                result.append(job_json(owned_job(principal, job.pk)))
            except Problem:
                continue
        return {'exports': result}
    data = body_json(request, 16384)
    if set(data) - {'dataset', 'filters', 'format', 'max_credits'}:
        raise Problem('invalid_export', 'Unknown export request fields.')
    job = create_export(principal, data.get('dataset'), filters=data.get('filters'), format=data.get('format', 'jsonl'), max_credits=data.get('max_credits'), request_id=request.headers.get('Idempotency-Key'))
    return JsonResponse(job_json(job), status=202)


@endpoint()
def detail(request, principal, job_id):
    return job_json(owned_job(principal, job_id))


@endpoint()
def artifact(request, principal, job_id):
    job, content = download(principal, job_id)
    response = HttpResponse(content, content_type='application/x-ndjson; charset=utf-8' if job.format == 'jsonl' else 'text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="kwip-export-{job.pk}.{job.format}"'
    response['X-Export-Status'] = job.status
    return response
