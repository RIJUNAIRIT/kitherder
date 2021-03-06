# Create your views here.

from django.template import Context, loader
from django.shortcuts import render_to_response
from django.http import HttpResponse
from django.template import RequestContext
from django import forms
from django.db.models import Q
from django.core.context_processors import csrf
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect

from matchmaker.models import Project, Division, Coordinator, Mentor, Mentee, Projectstatus, MenteeInterestInProject, Milestone
from matchmaker.forms import ProjectForm, MentorMenteeProjectForm, CoordinatorProjectForm, MenteeEditProjectForm, MentorEditProjectForm, CoordinatorEditProjectForm, MentorMenteeMilestoneForm

import json
import requests

from matchmaker.utils import findUserRole, belongToProject, findDivisionsCorrespondingCoordinator, findDivisionsCorrespondingMentorMentee,getMozillianDataByUser, getMozillianGroupsbyUser, getVouchedMembersofDivision, getMozillianSkillsByUser


	
# some extra forms #

class SearchForm(forms.Form):
    searchterm = forms.CharField(max_length=500, required=False)
    noncompleted = forms.BooleanField(initial=True,required=False)
    matchskills = forms.BooleanField(required=False)
    mozilliangroups = forms.BooleanField(required=False)
	
class SearchMenteeForm(forms.Form):
	project = forms.IntegerField(widget=forms.HiddenInput)
	searchterm = forms.CharField(max_length=500,required=False)
	matchskills = forms.BooleanField(required=False)
	
class SearchMentorForm(forms.Form):
	project = forms.IntegerField(widget=forms.HiddenInput)
	searchterm = forms.CharField(max_length=500,required=False)
	matchskills = forms.BooleanField(required=False)
	
class DivisionGroupForm(forms.Form):
	division = forms.IntegerField(widget=forms.HiddenInput)

	def __init__(self,*args,**kwargs):
		email = kwargs.pop("email")     # client is the parameter passed from views.py
		super(DivisionGroupForm, self).__init__(*args,**kwargs)
		self.fields['mozilliangroup'] = forms.ChoiceField(label="", choices=[(item, item) for item in getMozillianGroupsbyUser(email)])
		

# end of extra forms #	
	
	
	
	
@login_required
def myprojects(request):
	role = findUserRole(request.user.email)	
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))
	
	if role == "mentor":
		myprojectslist = Project.objects.filter(mentor_id__user_id__email=request.user.email)
	elif role == "mentee":
		myprojectslist = Project.objects.filter(mentee_id__user_id__email=request.user.email)
	elif role == "coordinator":
		divisionList = findDivisionsCorrespondingCoordinator(request.user.email)
		myprojectslist = Project.objects.filter(division_id__in = divisionList)
		
		if request.method == 'POST' and "approveproject" in request.POST:
			p = Project.objects.get(pk=request.POST['project'])
			c = Coordinator.objects.get(user_id__email=request.user.email)
			p.approved= True
			p.approved_by = c
			p.save()

	return render_to_response('matchmaker/templates/myprojects.html', {'myprojectslist': myprojectslist, 'role': role}, context_instance=RequestContext(request))	


@login_required	
def searchproject(request):
	# ASSUMPTION: By default, everyone can search and see everyone else's project (unless advanced search options/filters are used)
	
	role = findUserRole(request.user.email)
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))

	
	if request.method == 'POST':
		searched = 1;
		form = SearchForm(request.POST)
		if form.is_valid():
			searchterm = form.cleaned_data['searchterm']

			if searchterm == '':
				resultprojectslist = Project.objects.all()		
			else:
				resultprojectslist = Project.objects.filter(Q(division_id__division_name__icontains=searchterm) | Q(project_name__icontains=searchterm) | Q(project_description__icontains=searchterm) | Q(skills_required__icontains=searchterm) | Q(parent_project_id__project_name__icontains=searchterm))
			
			divisionerror = "";
			skillserror = "";
			# advanced option: refine by if only in user's group (warning: if user is not in group, will return no results)
			if form.cleaned_data['mozilliangroups']:
				if role == 'coordinator':
					division = findDivisionsCorrespondingCoordinator(request.user.email)[0]
					resultprojectslist = resultprojectslist.filter(division_id = division.pk)
				else:
					try:
						userdivision = findDivisionsCorrespondingMentorMentee(request.user.email)		
						resultprojectslist = resultprojectslist.filter(division_id__in=[item.pk for item in userdivision])
					except Exception as e:
						divisionerror = "<li>Search result does not filter by divisions related to your Mozillian groups</li>"
			
			# advanced option: refine by showing non completed projects (default checked)
			if form.cleaned_data['noncompleted']:
				resultprojectslist = resultprojectslist.exclude(project_status_id__status = "completed")

			# advanced option: only matching user's skills (warning, if user have not entered skills in mozillian, will return no results)
			if form.cleaned_data['matchskills']:
				try:
					filter = Q()
					for skill in getMozillianSkillsByUser(request.user.email):
						filter	= filter | Q(skills_required__icontains = skill)
				
					resultprojectslist = resultprojectslist.filter(filter)
				except Exception as e:
					skillserror = "<li>Search result does not filter by your skills.</li>"
			
			print skillserror
			
			if divisionerror != "" or skillserror != "":
				error = "Mozillian is currently not available:<ul>"
				if divisionerror:
					error = error + divisionerror
				if skillserror:
					error = error + skillserror
				error = error + "</ul>"
				return render_to_response('matchmaker/templates/searchproject.html', {'resultprojectslist': resultprojectslist, 'role':role, 'form': form, 'error': error, 'searched': searched}, context_instance=RequestContext(request))
			
			
			return render_to_response('matchmaker/templates/searchproject.html', {'resultprojectslist': resultprojectslist, 'role':role, 'form': form, 'searched': searched}, context_instance=RequestContext(request))
			
			
	searched = 0;
	form = SearchForm()
	
	return render_to_response('matchmaker/templates/searchproject.html', {'form': form, 'role':role, 'searched': searched}, context_instance=RequestContext(request))


@login_required	
def projectdetail(request, project_id):
	status="nothing";
	role = findUserRole(request.user.email)
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))
	
	isbelong = belongToProject(request.user.email,project_id)
	
	if role == "coordinator":
		if request.method == 'POST' and "approveproject" in request.POST:
			p = Project.objects.get(pk=request.POST['project'])
			c = Coordinator.objects.get(user_id__email=request.user.email)
			p.approved= True
			p.approved_by = c
			p.save()
	
	

	theproject = Project.objects.get(pk=project_id)
	mycoordinatorlist = Coordinator.objects.select_related().filter(division_id=theproject.division_id)
	

	if request.method == 'POST' and 'deleteMilestone' in request.POST:
		m = Milestone.objects.get(pk=request.POST['milestone'])
		m.delete()
		status="deletedMilestone"
		
	# assume anyone can see the milestones list
	milestoneslist = Milestone.objects.select_related().filter(project_id=project_id)
	
	# check to see if user is a mentee and is not a member of the project, whether they have expressed interest already in the project
	expressedinterest = 0
	if not isbelong and role == "mentee":
		# if user has clicked on the express interest button
		if request.method == 'POST' and "expressinterest" in request.POST:
			mentee = Mentee.objects.get(user_id__email=request.user.email)
			interest = MenteeInterestInProject(project_id=theproject, mentee_id=mentee)
			interest.save()
		expressedinterest = MenteeInterestInProject.objects.filter(mentee_id__user_id__email=request.user.email,project_id=project_id).count()
		return render_to_response('matchmaker/templates/projectdetails.html', {'theproject': theproject, 'mycoordinatorlist': mycoordinatorlist, 'milestoneslist': milestoneslist, 'role': role, 'isbelong': isbelong, 'expressedinterest': expressedinterest, 'status': status}, context_instance=RequestContext(request))
	
	
	
	# check to see if user is a mentor and list all mentees who had expressed interest
	if (isbelong and role == "mentor") or role =="coordinator":
		# if user has clicked on select mentee to add a mentee from the "expressed interest" list
		# ASSUMPTION: mentors can add a mentee who has expressed interest in their project to the project but the triad still has to be approved_by coordinator
		# COROLLARY ASSUMPTION: a mentor can also add any mentee who is currently marked to be looking for a project (whether they have expressed interest or not)
		if request.method == 'POST' and "selectmentee" in request.POST:
			p = Project.objects.get(pk=request.POST['project'])
			m = Mentee.objects.get(user_id__email=request.POST['selectedmentee'])
			p.mentee_id = m
			p.save()
			theproject = Project.objects.get(pk=project_id)			
		
		expressedinterestlist = MenteeInterestInProject.objects.filter(project_id=project_id)

		return render_to_response('matchmaker/templates/projectdetails.html', {'theproject': theproject, 'mycoordinatorlist': mycoordinatorlist, 'milestoneslist': milestoneslist, 'role': role, 'isbelong': isbelong, 'expressedinterestlist': expressedinterestlist, 'status': status}, context_instance=RequestContext(request))
	return render_to_response('matchmaker/templates/projectdetails.html', {'theproject': theproject, 'mycoordinatorlist': mycoordinatorlist, 'milestoneslist': milestoneslist, 'role': role, 'isbelong': isbelong, 'expressedinterest': expressedinterest, 'status': status}, context_instance=RequestContext(request))

@login_required	
def projectedit(request, project_id):
	role = findUserRole(request.user.email)
	redirecturl = '/matchmaker/project/' + str(project_id)
	
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))
	
	isbelong = belongToProject(request.user.email,project_id)
	if (not isbelong):
		return redirect(redirecturl, context_instance=RequestContext(request))
	
	theproject = Project.objects.get(pk=project_id)
	
	if role == "mentee":
		if request.method == 'POST':
			submitform = MenteeEditProjectForm(request.POST, instance=theproject)
			if submitform.is_valid():
				submitform.save()
				return redirect(redirecturl, context_instance=RequestContext(request))		
		submitform = MenteeEditProjectForm(instance=theproject)

	elif role == "coordinator":
		if request.method == 'POST':
			submitform = CoordinatorEditProjectForm(request.POST, instance=theproject)
			if submitform.is_valid():
				submitform.save()
				return redirect(redirecturl, context_instance=RequestContext(request))
		submitform = CoordinatorEditProjectForm(instance=theproject)

	else:
		if request.method == 'POST':
			submitform = MentorEditProjectForm(request.POST, instance=theproject)
			if submitform.is_valid():
				submitform.save()
				return redirect(redirecturl, context_instance=RequestContext(request))
		submitform = MentorEditProjectForm(instance=theproject)
	
	return render_to_response('matchmaker/templates/projectedit.html', {'theproject': theproject, 'role': role, 'isbelong': isbelong, 'submitform': submitform}, context_instance=RequestContext(request))


@login_required	
def submitproject(request):
	role = findUserRole(request.user.email)	
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))
	# presenting and inputing forms
	if role == "coordinator":
		if request.method == 'POST':
			submitform = CoordinatorProjectForm(request.POST)
			if submitform.is_valid():
				# assigning all values from form to the object newproject
				newproject = submitform.save(commit=False)
				
				# allow coordinator to approve during submission
				if ("approved" in request.POST):
					currcoordinator = Coordinator.objects.get(user_id__email=request.user.email)
					newproject.approved_by = currcoordinator
				
				# ASSUMPTION that terms have been agreed on already
				newproject.terms_agree = True
				
				newproject.save()
				return redirect('/matchmaker/', context_instance=RequestContext(request))		
		else:
			submitform = CoordinatorProjectForm()
			# ASSUMPTION: coordinators can only submit projects to the division they are coordinating for
			divisionlist = findDivisionsCorrespondingCoordinator(request.user.email)
			submitform.fields["division_id"].queryset = divisionlist
			
			# ASSUMPTION: parent project must be not completed, so user can only select from a list of non-completed projectsZ
			parentprojectlist = Project.objects.exclude(project_status_id__status="completed")
			submitform.fields["parent_project_id"].queryset = parentprojectlist
			
	else:
		if request.method == 'POST':
			submitform = MentorMenteeProjectForm(request.POST)
			if submitform.is_valid():
				# assigning all values from form to the object newproject
				newproject = submitform.save(commit=False)
				
				# setting default status as submitted
				defaultProjectstatus = Projectstatus.objects.get(status="submitted")
				newproject.project_status_id = defaultProjectstatus
				
				
				# setting default mentor if logged in user is a mentor		
				if role == "mentor":
					mentor = Mentor.objects.get(user_id__email=request.user.email)				
					newproject.mentor_id = mentor
				elif role == "mentee":
					mentee = Mentee.objects.get(user_id__email=request.user.email)
					newproject.mentee_id = mentee
								
				newproject.save()
				return redirect('/matchmaker/', context_instance=RequestContext(request))
		else:
			submitform = MentorMenteeProjectForm()
			# ASSUMPTION: mentor can only submit projects to a division with mozillian group they belong to, if they do not belong to a group, they cannot submit a project yet
			if role == "mentor":
				try:
					divisionlist = findDivisionsCorrespondingMentorMentee(request.user.email)
				except Exception as e:
					return render_to_response('matchmaker/templates/submitproject.html', {'submitform': submitform, 'cannotsubmit': 2, 'role':role,}, context_instance=RequestContext(request))

				if len(divisionlist) > 0: 	
					submitform.fields["division_id"].queryset = divisionlist
				else:
					return render_to_response('matchmaker/templates/submitproject.html', {'submitform': submitform, 'cannotsubmit': 1, 'role':role,}, context_instance=RequestContext(request))

			# ASSUMPTION: parent project must be not completed, so user can only select from a list of non-completed projects, but parent projects can be from any division
			parentprojectlist = Project.objects.exclude(project_status_id__status="completed")
			submitform.fields["parent_project_id"].queryset = parentprojectlist
			
	return render_to_response('matchmaker/templates/submitproject.html', {'submitform': submitform, 'role':role,}, context_instance=RequestContext(request))



@login_required	
def searchmentee(request):
	# currently restricted to be used only by only used by coordinators or mentors
	# ASSUMPTION all mentees that are looking for projects is searchable (since mentees are not necessariy vouched and have not necessarily joined a group yet)
	
	role = findUserRole(request.user.email)	
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))
	if role == "mentee":
		return redirect('/matchmaker/myprojects', context_instance=RequestContext(request))

	project =""
	if request.method == 'POST':
		project = request.POST['project']
		
	if request.method == 'POST' and 'searchterm' in request.POST:
		searched = 1;
		form = SearchMenteeForm(request.POST)
		if form.is_valid():
			project = form.cleaned_data['project']
			searchterm = form.cleaned_data['searchterm']
			resultmenteeslist = Mentee.objects.filter(user_id__email__icontains=searchterm, is_looking=True)
			
			# advanced option: show mentees whose skills matches the projects' needs (warning, if user have not entered skills in mozillian, user will not be included in this search)
			if form.cleaned_data['matchskills']:
				projectskills = Project.objects.filter(pk=project)[0].skills_required
				
				#check each mentee to see if they have a single skill that matches one of the project's
				for mentee in resultmenteeslist:
					numskillsmatched = 0

					try:
						for skill in getMozillianSkillsByUser(mentee.user_id.email):
							print skill
							if projectskills.lower().find(skill.lower()) != -1:
								numskillsmatched = numskillsmatched + 1

						if numskillsmatched < 1:
							resultmenteeslist = resultmenteeslist.exclude(pk=mentee.pk)
					except Exception as e:
						error = "Skills from Mozillian currently not available. Showing search results not filtered by skills."
						return render_to_response('matchmaker/templates/menteefinder.html', {'resultmenteeslist': resultmenteeslist, 'form': form, 'searched': searched, 'error': error, 'project': project}, context_instance=RequestContext(request))		
			
			
			return render_to_response('matchmaker/templates/menteefinder.html', {'resultmenteeslist': resultmenteeslist, 'form': form, 'searched': searched, 'project': project}, context_instance=RequestContext(request))		
			
	if request.method =='POST' and 'selectedmentee' in request.POST:
		p = Project.objects.get(pk=request.POST['project'])
		m = Mentee.objects.get(user_id__email=request.POST['selectedmentee'])
		p.mentee_id = m
		p.save()
		return render_to_response('matchmaker/templates/menteefindersuccess.html', {'mentee': request.POST['selectedmentee'], 'project_name': p.project_name}, context_instance=RequestContext(request))		
	
	searched = 0;
	form = SearchMenteeForm(initial={'project': project})
	resultmenteeslist = Mentee.objects.filter(is_looking=True)
	return render_to_response('matchmaker/templates/menteefinder.html', {'resultmenteeslist': resultmenteeslist, 'form': form, 'searched': searched, 'project': project}, context_instance=RequestContext(request))
	
	
@login_required	
def searchmentor(request):
	# currently restricted to be used only by only used by coordinators
	role = findUserRole(request.user.email)	
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))
	if role != "coordinator":
		return redirect('/matchmaker/myprojects', context_instance=RequestContext(request))

	project = ""
	searched = 0
	form = SearchMentorForm()
	resultmentorslist = Mentor.objects.none
	divisionmentorlist = Mentor.objects.none
	
	divisionslist = findDivisionsCorrespondingCoordinator(request.user.email)
	
	for division in divisionslist:
		try:
			divisionmentorlist = getVouchedMembersofDivision(division.pk)
		except Exception as e:
			error = "Unable to return list of mentors in the group relating to your division. Check if Mozillian is up."
			return render_to_response('matchmaker/templates/mentorfinder.html', {'resultmentorslist': resultmentorslist, 'form': form, 'error': error, 'searched': searched, 'project': project}, context_instance=RequestContext(request))
			
	
	if request.method == 'POST':
		project = request.POST['project']
	
		
	if request.method == 'POST' and 'searchterm' in request.POST:
		searched = 1;
		form = SearchMentorForm(request.POST)
		if form.is_valid():
			project = form.cleaned_data['project']
			searchterm = form.cleaned_data['searchterm']
			searchedmentorslist = Mentor.objects.filter(user_id__email__icontains=searchterm)
					
			
			# further filter based on only mentors that are in the coordinator's division
			resultmentorslist = searchedmentorslist.filter(pk__in = [item.pk for item in divisionmentorlist])
			
			# advanced option: show mentors whose skills matches the projects' needs (warning, if user have not entered skills in mozillian, user will not be included in this search)
			if form.cleaned_data['matchskills']:
				projectskills = Project.objects.filter(pk=project)[0].skills_required
				
				#check each mentor to see if they have a single skill that matches one of the project's
				for mentor in resultmentorslist:
					numskillsmatched = 0
					
					mentorskills = getMozillianSkillsByUser(mentor.user_id.email)
					print mentorskills;

					try:
						for skill in mentorskills:
							if projectskills.lower().find(skill.lower()) != -1:
								numskillsmatched = numskillsmatched + 1

						if numskillsmatched < 1:
							resultmentorslist = resultmentorslist.exclude(pk=mentor.pk)
					except Exception as e:
						error = "Skills from Mozillian currently not available. Showing search results not filtered by skills."
						return render_to_response('matchmaker/templates/mentorfinder.html', {'resultmentorslist': resultmentorslist, 'form': form, 'searched': searched, 'error': error, 'project': project}, context_instance=RequestContext(request))	
			
			
			return render_to_response('matchmaker/templates/mentorfinder.html', {'resultmentorslist': resultmentorslist, 'form': form, 'searched': searched, 'project': project}, context_instance=RequestContext(request))		
			
	if request.method =='POST' and 'selectedmentor' in request.POST:
		p = Project.objects.get(pk=request.POST['project'])
		m = Mentor.objects.get(user_id__email=request.POST['selectedmentor'])
		p.mentor_id = m
		p.save()
		return render_to_response('matchmaker/templates/mentorfindersuccess.html', {'mentor': request.POST['selectedmentor'], 'project_name': p.project_name}, context_instance=RequestContext(request))		
	
	searched = 0;
	form = SearchMentorForm(initial={'project': project})

	resultmentorslist = divisionmentorlist
		
	return render_to_response('matchmaker/templates/mentorfinder.html', {'resultmentorslist': resultmentorslist, 'form': form, 'searched': searched, 'project': project}, context_instance=RequestContext(request))
	
@login_required	
def milestoneadd(request):
	role = findUserRole(request.user.email)	
	
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))

	project =""
	if request.method == 'POST':
		project = request.POST['project_id']
	
	form = MentorMenteeMilestoneForm(initial={'project_id': project, 'milestone_status': 'started'})
		
	if request.method =='POST' and 'submit' in request.POST:
		form = MentorMenteeMilestoneForm(request.POST)
		if form.is_valid():
			# assigning all values from form to the object new milestone
			newmilestone = form.save(commit=False)
			
			newmilestone.save()
			return render_to_response('matchmaker/templates/milestoneaddsuccess.html', {}, context_instance=RequestContext(request))		
		
	return render_to_response('matchmaker/templates/milestoneadd.html', {'form': form, 'project': project}, context_instance=RequestContext(request))
	
@login_required	
def milestoneedit(request, milestoneID):
	role = findUserRole(request.user.email)	
	
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))

	project =""
	if request.method == 'POST':
		themilestone = Milestone.objects.get(pk=milestoneID)
	
	form = MentorMenteeMilestoneForm(instance=themilestone)
	
	
	if request.method =='POST' and 'submit' in request.POST:
		form = MentorMenteeMilestoneForm(request.POST, instance=themilestone)
		if form.is_valid():
			# assigning all values from form to the object newproject
			newmilestone = form.save()
			
			return render_to_response('matchmaker/templates/milestoneaddsuccess.html', {}, context_instance=RequestContext(request))		
		
	return render_to_response('matchmaker/templates/milestoneedit.html', {'form': form}, context_instance=RequestContext(request))
	
	
@login_required	
def managedivision(request):
	role = findUserRole(request.user.email)
	if role == "":
		return redirect('/entrance/register/', context_instance=RequestContext(request))
	
	if role != "coordinator":
		return redirect('/matchmaker/myprojects/', context_instance=RequestContext(request))
	
	
	division = findDivisionsCorrespondingCoordinator(request.user.email)[0]	

	
	if request.method == 'POST' and 'submit' in request.POST:
		form = DivisionGroupForm(request.POST, email=request.user.email)
		if form.is_valid():
			thedivision = Division.objects.get(pk=form.cleaned_data['division'])
			thedivision.mozillian_group = form.cleaned_data['mozilliangroup']
			thedivision.save()			
	
	try:
		testgroups = getMozillianGroupsbyUser(request.user.email)
		
	except Exception as e:
		error = "Cannot retrieve groups from Mozillian. Check to see if Mozillian is up."
		form = ""
		return render_to_response('matchmaker/templates/managedivision.html', {'form': form, 'division': division, 'error':error, 'role':role}, context_instance=RequestContext(request))

	form = DivisionGroupForm(initial={'division':division.pk}, email=request.user.email)
		
	return render_to_response('matchmaker/templates/managedivision.html', {'form': form, 'division': division, 'role':role}, context_instance=RequestContext(request))
