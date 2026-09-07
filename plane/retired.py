"""Terminal responses for the retired hosted PyScoped service; never parse bodies."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def retired(request, **kwargs):
    response = JsonResponse({
        "error": "hosted_pyscoped_retired",
        "message": "Hosted ingestion, accounts, billing, and dashboards have been retired. PyScoped 2.0 is a free Django library that runs in your database.",
        "migration": "https://kwip.tech/docs/migration.md",
    }, status=410)
    response["Cache-Control"] = "no-store"
    response["Link"] = '<https://kwip.tech/docs/migration.md>; rel="deprecation"'
    return response

def health(request):
    return JsonResponse({"status": "ok", "service": "kwiptech", "pyscoped": "2.0.0", "ingestion": "retired"})
