from django.shortcuts import render
from django.http import HttpResponse

import logging
from django.http import HttpResponse

logger = logging.getLogger(__name__)

def hello(request):
    logger.info("Hello view accessed")
    return HttpResponse("Hello, world!")
