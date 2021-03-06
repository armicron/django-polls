from django.contrib.auth import get_user_model
from django.core.urlresolvers import resolve
from django.forms.models import model_to_dict
from tastypie import fields
from tastypie.authorization import Authorization, ReadOnlyAuthorization
from tastypie.authentication import MultiAuthentication, BasicAuthentication, SessionAuthentication
from tastypie.resources import ModelResource, ALL
from tastypie.exceptions import ImmediateHttpResponse
from tastypie import http
from polls.models import Poll, Choice, Vote
from exceptions import PollClosed, PollNotOpen, PollNotAnonymous, PollNotMultiple


'''
    Api("v1/poll")
    POST /poll/ -- create a new poll, shall allow to post choices in the same API call
    POST /choice/ -- add a choice to an existing poll
    POST /vote/ -- vote on poll with pk
    PUT /choice/ -- update choice data
    PUT /poll/ -- update poll data
    GET /poll/ -- retrieve the poll information, including choice details
    GET /result/ -- retrieve the statistics on the poll.
    This shall return a JSON formatted like so. Note the actual statistics calculation shall be implemented
        in poll.service.stats (later on, this will be externalized into a batch job).
'''


class UserResource(ModelResource):
    def limit_list_by_user(self, request, object_list):
        """
        limit the request object list to its own profile, except
        for superusers. Superusers get a list of all users

        note that for POST requests tastypie internally
        queries get_object_list, and we should return a valid
        list
        """
        view, args, kwargs = resolve(request.path)
        if request.method == 'GET' and not 'pk' in kwargs and not request.user.is_superuser:
            return object_list.filter(pk=request.user.pk)
        return object_list

    def get_object_list(self, request):
        object_list = super(UserResource, self).get_object_list(request)
        object_list = self.limit_list_by_user(request, object_list)
        return object_list

    class Meta:
        queryset = get_user_model().objects.all()
        allowed_methods = ['get']
        resource_name = 'user'
        always_return_data = True
        authentication = MultiAuthentication(BasicAuthentication(), SessionAuthentication())
        authorization = ReadOnlyAuthorization()
        excludes = ['date_joined', 'password', 'is_superuser', 'is_staff', 'is_active', 'last_login', 'first_name', 'last_name']
        filtering = {
            'username': ALL,
        }


class PollResource(ModelResource):
    # POST, GET, PUT
    #user = fields.ForeignKey(UserResource, 'user')
    def obj_create(self, bundle, **kwargs):
        return super(PollResource, self).obj_create(bundle, user=bundle.request.user)

    def dehydrate(self, bundle):
        choices = Choice.objects.filter(poll=bundle.data['id'])
        bundle.data['choices'] = [model_to_dict(choice) for choice in choices]
        return bundle

    def alter_detail_data_to_serialize(self, request, data):
        data.data['already_voted'] = Poll.objects.get(pk=data.data.get('id')).already_voted(user=request.user)
        return data

    class Meta:
        queryset = Poll.objects.all()
        allowed_methods = ['get','post','put']
        resource_name = 'poll'
        always_return_data = True
        authentication = MultiAuthentication(BasicAuthentication(), SessionAuthentication())
        authorization = Authorization()


class ChoiceResource(ModelResource):
    poll = fields.ToOneField(PollResource, 'poll')

    class Meta:
        queryset = Choice.objects.all()
        allowed_methods = ['post','put']
        authentication = MultiAuthentication(BasicAuthentication(), SessionAuthentication())
        authorization = Authorization()
        resource_name = 'choice'
        always_return_data = True


class VoteResource(ModelResource):
    user = fields.ToOneField(UserResource, 'user')
    choice = fields.ToOneField(ChoiceResource, 'choice')
    poll = fields.ToOneField(PollResource, 'poll')

    def obj_create(self, bundle, **kwargs):
        poll = PollResource().get_via_uri(bundle.data.get('poll'))
        if not poll.already_voted(bundle.request.user):
            try:
                poll.vote(choices=bundle.data.get('choice'), user=bundle.request.user)
                raise ImmediateHttpResponse(response=http.HttpCreated())
            except (PollClosed, PollNotOpen, PollNotAnonymous, PollNotMultiple):
                raise ImmediateHttpResponse(response=http.HttpForbidden('not allowed'))
        else:
            raise ImmediateHttpResponse(response=http.HttpForbidden('already voted'))


    class Meta:
        queryset = Vote.objects.all()
        allowed_methods = ['post']
        authentication = MultiAuthentication(BasicAuthentication(), SessionAuthentication())
        #authorization = Authorization()
        resource_name = 'vote'
        always_return_data = True


class ResultResource(ModelResource):
    def dehydrate(self, bundle):
        percentage = Poll.objects.get(pk=bundle.data['id']).count_percentage()
        labels = [choice.choice for choice in Choice.objects.filter(poll=bundle.data['id'])]
        bundle.data['stats'] = dict(values=percentage, labels=labels, votes=len(labels))
        return bundle

    class Meta:
        queryset = Poll.objects.all()
        allowed_methods = ['get']
        authentication = MultiAuthentication(BasicAuthentication(), SessionAuthentication())
        authorization = Authorization()
        resource_name = 'result'
        always_return_data = True
        excludes = ['description', 'start_votes', 'end_votes', 'is_anonymous', 'is_multiple', 'is_closed', 'reference']

