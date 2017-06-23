from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.template import loader

from website import functions
from website.config import *
from website.models import NL, Command, URL, User, URLTag, \
    Annotation, AnnotationJudgement, AnnotationProgress
from website.utils import get_nl, get_command, get_url, get_tag

WHITE_LIST = {'find', 'xargs'}
BLACK_LIST = {'cpp', 'g++', 'java', 'perl', 'python', 'ruby',
              'nano', 'emacs', 'vim'}


def json_response(d={}, status='SUCCESS'):
    d.update({'status': status})
    resp = JsonResponse(d)
    return resp


def access_code_required(f):
    @functions.wraps(f)
    def g(request, *args, **kwargs):
        try:
            access_code = request.COOKIES['access_code']
        except KeyError:
            return login(request)
        return f(request, *args, access_code=access_code, **kwargs)
    return g


def safe_get_user(access_code):
    try:
        user = User.objects.get(access_code=access_code)
        return user
    except ObjectDoesNotExist:
        print('User {} does not exist!'.format(access_code))
        return None


@access_code_required
def collect_page(request, access_code):
    """
    Collection Interface.
    """
    template = loader.get_template('annotator/collect_page.html')
    user = safe_get_user(access_code)

    utility = request.GET.get('utility')
    url = get_url(request.GET.get('url'))

    # search for existing annotations
    annotation_dict = {}
    if access_code == admin_access_code:
        annotation_list = Annotation.objects.filter(url=url)
    else:
        annotation_list = Annotation.objects.filter(url=url, annotator=user)
    for annotation in annotation_list:
        key = '__NL__{}__Command__{}'.format(annotation.nl.str, annotation.cmd.str)
        if not key in annotation_dict:
            annotation_dict[key] = (annotation.cmd.str, annotation.nl.str)

    annotation_list = sorted(annotation_dict.values(), key=lambda x: x[0])

    hypothes_prefix = "https://via.hypothes.is/"
    context = {
        'utility': utility,
        'url': hypothes_prefix + url.str,
        'annotation_list': annotation_list,
        'completed': False,
        'access_code': access_code
    }

    try:
        record = AnnotationProgress.objects.get(annotator=user, url=url)
        if record.status == 'completed':
            context['completed'] = True
    except ObjectDoesNotExist:
        pass

    return HttpResponse(template.render(context=context, request=request))


@access_code_required
def submit_annotation(request, access_code):
    user = User.objects.get(access_code=access_code)
    url = get_url(request.GET.get('url'))
    nl = get_nl(request.GET.get('nl'))
    tag = get_tag(request.GET.get('utility'))
    command = get_command(request.GET.get('command'))
    command.tags.add(tag)

    annotation = Annotation.objects.create(
        url=url, nl=nl, cmd=command, annotator=user)

    if not AnnotationProgress.objects.filter(annotator=user, url=url):
        AnnotationProgress.objects.create(annotator=user, url=url, status='in-progress')

    resp = json_response({'nl': annotation.nl.str, 'command': annotation.cmd.str},
                         status='ANNOTATION_SAVED')

    return resp


@access_code_required
def submit_edit(request, access_code):
    user = User.objects.get(access_code=access_code)
    url = get_url(request.GET.get('url'))
    original_nl = get_nl(request.GET.get('original_nl'))
    original_command = get_command(request.GET.get('original_command'))
    nl = get_nl(request.GET.get('nl'))
    command = get_command(request.GET.get('command'))

    Annotation.objects.filter(url=url, nl=original_nl, cmd=original_command).delete()

    annotation = Annotation.objects.create(url=url, nl=nl, cmd=command, annotator=user)

    resp = json_response({'nl': annotation.nl.str, 'command': annotation.cmd.str},
                         status='EDIT_SAVED')

    return resp


@access_code_required
def delete_annotation(request, access_code):
    url = get_url(request.GET.get('url'))
    nl = get_nl(request.GET.get('nl'))
    command = get_command(request.GET.get('command'))

    Annotation.objects.filter(url=url, nl=nl, cmd=command).delete()

    return json_response(status='DELETION_SUCCESS')


@access_code_required
def update_progress(request, access_code):
    user = User.objects.get(access_code=access_code)
    url = get_url(request.GET.get('url'))
    status = request.GET.get('status')

    try:
        record = AnnotationProgress.objects.get(annotator=user, url=url)
        record.status = status
        record.save()
    except ObjectDoesNotExist:
        AnnotationProgress.objects.create(annotator=user, url=url, status=status)

    return json_response(status='PROGRESS_UPDATED')


@access_code_required
def previous_url(request, access_code):
    utility = request.GET.get('utility')
    current_url = request.GET.get('url')

    is_current_url = False
    prev_url = None

    for url_tag in URLTag.objects.filter(tag=utility).order_by('url__str'):
        print(url_tag.url.str, current_url)
        if url_tag.url.str == current_url:
            is_current_url = True
            break
        prev_url = url_tag.url

    if prev_url is not None:
        resp = json_response({'url': prev_url.str}, status="PREVIOUS_URL_SUCCESS")
    else:
        if is_current_url:
            resp = json_response(status='IS_FIRST_URL')
        else:
            resp = json_response(status='URL_DOES_NOT_EXIST')

    return resp


@access_code_required
def next_url(request, access_code):
    utility = request.GET.get('utility')
    current_url = request.GET.get('url')

    is_current_url = False
    next_url = None
    for url_tag in URLTag.objects.filter(tag=utility).order_by('url__str'):
        if is_current_url:
            next_url = url_tag.url
            break
        else:
            if url_tag.url.str == current_url:
                is_current_url = True

    if next_url is not None:
        resp = json_response({'url': next_url.str}, status='NEXT_URL_SUCCESS')
    else:
        if is_current_url:
            resp = json_response(status='IS_LAST_URL')
        else:
            resp = json_response(status='URL_DOES_NOT_EXIST')

    return resp


@access_code_required
def url_panel(request, access_code):
    """
    Display a list of urls for a particular utility.
    """
    template = loader.get_template('annotator/url_panel.html')
    user = safe_get_user(access_code)

    utility = request.GET.get('utility')

    url_list = []
    for url_tag in URLTag.objects.filter(tag=utility).order_by('url__str'):
        try:
            record = AnnotationProgress.objects.get(annotator=user, url=url_tag.url)
            url_list.append((url_tag.url, record.status))
        except ObjectDoesNotExist:
            if Annotation.objects.filter(url=url_tag.url):
                url_list.append((url_tag.url, 'others-in-progress'))
            else:
                url_list.append((url_tag.url, ''))

    context = {
        'utility': utility,
        'url_list': url_list
    }
    if user:
        context['access_code'] = access_code

    return HttpResponse(template.render(context=context, request=request))


@access_code_required
def utility_panel(request, access_code):
    """
    Display all the utilities to annotate.
    """
    template = loader.get_template('annotator/utility_panel.html')
    user = safe_get_user(access_code)

    utilities_in_progress = set([])
    for obj in Annotation.objects.values('cmd'):
        cmd = get_command(obj['cmd'])
        for tag in cmd.tags.all():
            utilities_in_progress.add(tag.str)

    utilities = []
    for obj in URLTag.objects.values('tag').annotate(the_count=Count('tag'))\
            .order_by('-the_count'):
        if obj['tag'] in WHITE_LIST or obj['tag'] in BLACK_LIST:
            continue
        if obj['tag'] in utilities_in_progress:
            utilities.append((obj['tag'], 'in-progress'))
        else:
            utilities.append((obj['tag'], ''))

    utility_groups = []
    for i in range(0, len(utilities), 20):
        utility_group = utilities[i:i+20]
        if len(utility_group) > 10:
            utility_groups.append([utility_group[:10], utility_group[10:]])
        else:
            utility_groups.append([utility_group[:10], []])

    context = {
        'utility_groups': utility_groups
    }
    if user:
        context['access_code'] = access_code

    return HttpResponse(template.render(context=context, request=request))

# --- Registration & Login --- #

@access_code_required
def user_logout(request, access_code):
    resp = json_response(status='LOGOUT_SUCCESS')
    resp.delete_cookie('access_code')
    return resp


def user_login(request):
    access_code = request.GET.get('access_code')
    if User.objects.filter(access_code=access_code):
        resp = json_response({'access_code': access_code}, status='LOGIN_SUCCESS')
        resp.set_cookie('access_code', access_code)
    else:
        resp = json_response(status='USER_DOES_NOT_EXIST')
    return resp


def register_user(request):
    first_name = request.GET.get('firstname')
    last_name = request.GET.get('lastname')
    if User.objects.filter(first_name=first_name, last_name=last_name):
        resp = json_response({'firstname': first_name, 'lastname': last_name},
                             status='USER_EXISTS')
    else:
        access_code = first_name.lower() + '-' + last_name.lower()
        User.objects.create(access_code=access_code, first_name=first_name, last_name=last_name)
        resp = json_response({'firstname': first_name, 'lastname': last_name,
                              'access_code': access_code},
                             status='REGISTRATION_SUCCESS')
    return  resp


def login(request):
    """
    User login.
    """
    template = loader.get_template('annotator/login.html')

    return HttpResponse(template.render(context={}, request=request))
