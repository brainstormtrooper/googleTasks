# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Getting Things Gnome! - a personal organizer for the GNOME desktop
# Copyright (c) 2008-2009 - Lionel Dricot & Bertrand Rousseau
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
# -----------------------------------------------------------------------------

""" Google Tasks backend

Task reference: https://developers.google.com/google-apps/tasks/v1/reference/tasks#resource

Icon for this backend is part of google-tasks-chrome-extension (
http://code.google.com/p/google-tasks-chrome-extension/ ) published under
the terms of Apache License 2.0"""

import os
import httplib2
import uuid
import datetime
import webbrowser
import threading

from GTG import _
from GTG.backends.backendsignals import BackendSignals
from GTG.backends.genericbackend import GenericBackend
from GTG.backends.periodicimportbackend import PeriodicImportBackend
from GTG.backends.syncengine import SyncEngine, SyncMeme
from GTG.core import CoreConfig
from GTG.core.task import Task
from GTG.tools.interruptible import interruptible
from GTG.tools.logger import Log
from GTG.tools.dates import Date

# External libraries
from apiclient.discovery import build as build_service
from oauth2client.client import FlowExchangeError
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.file import Storage

class Backend(PeriodicImportBackend):
    # Credence for authorizing GTG as an app
    CLIENT_ID = '94851023623.apps.googleusercontent.com'
    CLIENT_SECRET = 'p6H1UGaDLAJjDaoUbwu0lNJz'

    _general_description = {
        GenericBackend.BACKEND_NAME: "backend_gtask",
        GenericBackend.BACKEND_HUMAN_NAME: _("Google Tasks"),
        GenericBackend.BACKEND_AUTHORS: ["Madhumitha Viswanathan",
                                         "Izidor Matušov",
                                         "Luca Invernizzi"],
        GenericBackend.BACKEND_TYPE: GenericBackend.TYPE_READWRITE,
        GenericBackend.BACKEND_DESCRIPTION:
            _("Synchronize your GTG tasks with Google Tasks \n\n"
              "Legal note: This product uses the Google Tasks API but is not "
              "endorsed or certified by Google Tasks"),\
        }

    _static_parameters = { \
        "period": { \
            GenericBackend.PARAM_TYPE: GenericBackend.TYPE_INT, \
            GenericBackend.PARAM_DEFAULT_VALUE: 5, },
        "is-first-run": { \
            GenericBackend.PARAM_TYPE: GenericBackend.TYPE_BOOL, \
            GenericBackend.PARAM_DEFAULT_VALUE: True, },
        }

    def __init__(self, parameters):
        '''
        See GenericBackend for an explanation of this function.
        Re-loads the saved state of the synchronization
        '''
        super(Backend, self).__init__(parameters)
        self.storage = None
        self.service = None
        self.authenticated = False
        #loading the list of already imported tasks
        self.data_path = os.path.join('backends/gtask/', "tasks_dict-%s" %\
                                     self.get_id())
        self.sync_engine = self._load_pickled_file(self.data_path, \
                                                   SyncEngine())

    def save_state(self):
        '''
        See GenericBackend for an explanation of this function.
        Saves the state of the synchronization.
        '''
        self._store_pickled_file(self.data_path, self.sync_engine)

    def initialize(self):
        """
        Intialize backend: try to authenticate. If it fails, request an authorization.
        """
        super(Backend, self).initialize()
        path = os.path.join(CoreConfig().get_data_dir(), 'backends/gtask', 'storage_file-%s' % self.get_id())
        # Try to create leading directories that path
        path_dir = os.path.dirname(path)
        if not os.path.isdir(path_dir):
            os.makedirs(path_dir)

        self.storage = Storage(path)
        self.authenticate()

    def authenticate(self):
        """ Try to authenticate by already existing credences or request an authorization """
        self.authenticated = False

        credentials = self.storage.get()
        if credentials is None or credentials.invalid == True:
            self.request_authorization()
        else:
            self.apply_credentials(credentials)

    def apply_credentials(self, credentials):
        """ Finish authentication or request for an authorization by applying the credentials """
        http = httplib2.Http()
        http = credentials.authorize(http)

        # Build a service object for interacting with the API.
        self.service = build_service(serviceName='tasks', version='v1', http=http,
                    developerKey='AIzaSyAmUlk8_iv-rYDEcJ2NyeC_KVPNkrsGcqU')

        self.authenticated = True

    def _authorization_step2(self, code):
        credential = self.flow.step2_exchange(code)

        self.storage.put(credential)
        credential.set_store(self.storage)

        return credential

    def request_authorization(self):
        """ Make the first step of authorization and open URL for allowing the access """
        self.flow = OAuth2WebServerFlow(client_id=self.CLIENT_ID,
            client_secret=self.CLIENT_SECRET,
            scope='https://www.googleapis.com/auth/tasks',
            user_agent='GTG')

        oauth_callback = 'oob'
        url = self.flow.step1_get_authorize_url(oauth_callback)
        browser_thread = threading.Thread(target=lambda: webbrowser.open_new(url))
        browser_thread.daemon = True
        browser_thread.start()

        # Request the code from user
        BackendSignals().interaction_requested(self.get_id(), _(
            "You need to <b>authorize GTG</b> to access your tasks on <b>Google</b>.\n"
            "<b>Check your browser</b>, and follow the steps there.\n"
            "When you are done, press 'Continue'."),
            BackendSignals().INTERACTION_TEXT,
            "on_authentication_step")

    def on_authentication_step(self, step_type="", code=""):
        """ First time return specification of dialog.
            The second time grab the code and make the second, last
            step of authorization, afterwards apply the new credentials """

        if step_type == "get_ui_dialog_text":
            return _("Code request"), _("Paste the code Google has given you"
                    "here")
        elif step_type == "set_text":
            try:
                credentials = self._authorization_step2(code)
            except FlowExchangeError, e:
                # Show an error to user and end
                self.quit(disable = True)
                BackendSignals().backend_failed(self.get_id(), 
                            BackendSignals.ERRNO_AUTHENTICATION)
                return

            self.apply_credentials(credentials)
            # Request periodic import, avoid waiting a long time
            self.start_get_tasks()
            
    def get_tasklist(self, gtaskID):
        '''
        Returns the tasklist id of a given task
        
        @param gtaskID: the id of the Google Task we're looking for
        '''
        # Wait until authentication
        if not self.authenticated:
            return
       
        # FIXME: this needs to be split into 2 functions - we may need to explicitly ask ggl if the task has been moved to a different list...
        # CHANGES: checks if the task list data is already stored with the local task.... no, not anymore, not safe...
        """
        try:
            tid = self.sync_engine.get_local_id(gtaskID)
            # if self.datastore.has_task(tid):
            Log.debug('[ii] Local tid for gtaskID ' + str(gtaskID) + ' is  ' + str(tid))
            task = self.datastore.get_task(tid)
            localglistID = task.get_attribute('gtasklistID')
            Log.debug('[ii] ggl Tasklist id attribute is ' + localglistID)
            localglistTitle = task.get_attribute('gtasklistTitle')
            
            taskslist = {}
            taskslist['title']=localglistTitle
            taskslist['id']=localglistID
            
            return taskslist
            
        except:
        """
            
        Log.debug('[ii] Hunting for list containing gtask ' + gtaskID )


        #Loop through all the tasklists
        tasklists=self.service.tasklists().list().execute()

        for taskslist in tasklists['items']:
            #print 'checking '+str(taskslist['title'])
            #Loop through all the tasks of a tasklist
            gtasklist = self.service.tasks().list(tasklist=taskslist['id']).execute()

            Log.debug("[ii] get_tasklist : checking google tasklist : " + taskslist['title'] + " for task " + gtaskID)
            if 'items' in gtasklist:
                for gtask in gtasklist['items']:
                    #print '\nchecking - '+str(gtask['title'])
                    #print gtask['id']
                    #print '\n'
                    #print task
                    Log.debug('[ii] get_tasklist : Comparing gtasklist item ID : ' + str(gtask['id']) + ' with gtask (?) : ' + str(gtaskID))
                    # CHANGES: replace cmp() with ==... "not" will pass if the left item is LESS than the right... 
                    # if not cmp(gtask['id'], task):
                    if gtask['id'] == gtaskID:
                        #
                        # They are the same...
                        # 
                        Log.debug('[ii] get_tasklist : the tassklist for ' + str(gtask['title']) + ' is - ' + str(taskslist['title']))
                        #return taskslist['id']        
                        # CHANGES: just give the whole thing so we can use the title and the id...
                        return taskslist
        Log.debug('[ww] get_tasklist : No match found for '+gtask['title'] +' - '+gtask['id'])
        return None
        
    def do_periodic_import(self):
        # Wait until authentication
        if not self.authenticated:
            return
        stored_task_ids = self.sync_engine.get_all_remote()
        gtask_ids = []
        #get all the tasklists
        tasklists=self.service.tasklists().list().execute()
        for taskslist in tasklists['items']:
          
            Log.debug('\n =========================== \n' + taskslist['title'] + '\n ===========================')
            
            gtasklist = self.service.tasks().list(tasklist=taskslist['id']).execute()
            
            if 'items' in gtasklist:
                for gtask in gtasklist['items']:
                    self._process_gtask(gtask['id'], taskslist)

                    #
                    # CHANGES: moved to the set_task function...
                    #
                    # self.get_tasklist(gtask['id'])

                    # CHANGES: No longer gets rid of most of the tasks whenever the current list changes...
                    # gtask_ids = [gtask['id'] for gtask in gtasklist['items']]
                    gtask_ids.append(gtask['id'])
            else:
                Log.debug('[ii] tasklist ' + taskslist['title'] + ' is empty')
                
        Log.debug('[ii] Checking for orphaned tasks')
        Log.debug('[ii] we have ' + str(len(gtask_ids)) + ' gtask IDs')
        Log.debug('[ii] we have ' + str(len(stored_task_ids)) + ' local IDs')
        for gtask in set(stored_task_ids).difference(set(gtask_ids)):
            Log.debug('[ii] deleting ' + gtask + ' from local tasks as it is not in stored gtask IDs')
            self.on_gtask_deleted(gtask, None)
    
        
        
        
        
         

    @interruptible
    def on_gtask_deleted(self, gtask, something):
        '''
        Callback, executed when a Google Task is deleted.
        Deletes the related GTG task.

        @param gtask: the id of the Google Task 
        @param something: not used, here for signal callback compatibility
        '''
        with self.datastore.get_backend_mutex():
            self.cancellation_point()
            try:
                tid = self.sync_engine.get_local_id(gtask)
            except KeyError:
                Log.debug('[ww] Failed to get local ID for gtask ' + gtask )
                return
            if self.datastore.has_task(tid):
                self.datastore.request_task_deletion(tid)
                self.break_relationship(remote_id = gtask)

    @interruptible
    def remove_task(self, tid):
        '''
        See GenericBackend for an explanation of this function.
        @param tid: a task id
        
        '''
        
        #print "\nremove_task\n"
        with self.datastore.get_backend_mutex():
            Log.debug('[ii] Attempting to remove task with local ID ' + tid )
            self.cancellation_point()
            try:
                gtaskID = self.sync_engine.get_remote_id(tid)
                Log.debug('[ii] ggl task to delete is ' + gtaskID )
            except KeyError:
                Log.debug('[ww] Failed to find ggl task for local ID ' + tid )
                # return
            #the remote task might have been already deleted manually (or by another app)
            try:
                Log.debug('[ii] trying to delete ggl task ... may not have a ggl ID')
                gtasklist=self.get_tasklist(gtaskID)
                self.service.tasks().delete(tasklist=gtasklist['id'], task=gtaskID).execute()
            except Exception, e:
                #FIXME:need to see if disconnected (?)...
                Log.debug('[ww] Failed to delete ggl taskfor local ID ' + tid + ' ... it may not exist.')
                Log.error(e)
            self.break_relationship(local_id = tid)

    def _process_gtask(self, gtaskID, gtasklist=None):
        '''
        Given a Google Task id, finds out if it must be synced to a GTG note and, 
        if so, it carries out the synchronization (by creating or updating a GTG
        task, or deleting itself if the related task has been deleted)

        @param gtaskID: a Google Task id
        @param gtasklistID: a Google tasklist id
        '''
        with self.datastore.get_backend_mutex():
            self.cancellation_point()
            
            # tid = self.sync_engine.get_local_id(gtaskID)
            rids = self.sync_engine.get_all_remote()
            if gtaskID in rids:
                Log.debug('[ww] gtask ' + str(gtaskID) + ' already exists in remote ids')
            
            is_syncable = self._google_task_is_syncable(gtaskID)
            action, tid = self.sync_engine.analyze_remote_id(gtaskID, \
                         self.datastore.has_task, \
                         self._google_task_exists(gtaskID), is_syncable)
            Log.debug("[ii] process gtask : processing google tasks (%s, %s)" % (action, is_syncable))
            """
            if gtasklistID != '0':
                gtasklist={}
                gtasklist['id']=gtasklistID
                gtasklist['title']=gtasklistTitle
            else:
                gtasklist=self.get_tasklist(gtaskID)
            """
            
            if gtasklist is None:
                gtasklist=self.get_tasklist(gtaskID)
            
            if action == SyncEngine.ADD:
                tid = str(uuid.uuid4())
                task = self.datastore.task_factory(tid)
                #
                # _populate_task uses the gtask id to get the actual gtask... so we only need the ID here...
                #
                self._populate_task(task, gtaskID, gtasklist)
                self.record_relationship(local_id = tid,\
                            remote_id = gtaskID, \
                            meme = SyncMeme(task.get_modified(),
                                            self.get_modified_for_task(gtaskID),
                                            self.get_id()))
                self.datastore.push_task(task)

            elif action == SyncEngine.REMOVE:
                
                self.service.tasks().delete(tasklist=gtasklist['id'], task=gtaskID).execute()
                self.break_relationship(local_id = tid)
                try:
                    self.sync_engine.break_relationship(remote_id = gtaskID)
                except KeyError:
                    pass
            
            elif action == SyncEngine.UPDATE:
                task = self.datastore.get_task(tid)
                meme = self.sync_engine.get_meme_from_remote_id(gtaskID)
                newest = meme.which_is_newest(task.get_modified(),
                                     self.get_modified_for_task(gtaskID))
                if newest == "remote":
                    self._populate_task(task, gtaskID, gtasklist)
                    meme.set_local_last_modified(task.get_modified())
                    meme.set_remote_last_modified(\
                                        self.get_modified_for_task(gtaskID))
                    self.save_state()
                #
                # Note: We don't need an "else:" ? ...
                # What if the local task is newesy? pr dp they automatically get uploaded on save?...
                #

            elif action == SyncEngine.LOST_SYNCABILITY:
                self._exec_lost_syncability(tid, gtaskID)
        

    @interruptible
    def set_task(self, task):
        '''
        See GenericBackend for an explanation of this function.
        
        '''
        #print "\nset_task\n"
        # Skip if not authenticated
        if not self.authenticated:
            return 

        self.cancellation_point()
        is_syncable = self._gtg_task_is_syncable_per_attached_tags(task)
        tid = task.get_id()
        with self.datastore.get_backend_mutex():
            action, gtask_id = self.sync_engine.analyze_local_id(tid, \
                           self.datastore.has_task(tid), self._google_task_exists, \
                                                        is_syncable)
            Log.debug("[ii] set task (gtg) : processing gtg (%s, %d)" % (action, is_syncable))
            if action == SyncEngine.ADD:
                
                try:
                    rid = self.sync_engine.get_remote_id(tid)
                    Log.debug('[ww] gtask ' + str(rid) + ' already exists in remote ids')
                except:
                    pass
                    
                gtask = {'title': ' ',}
                gtask_id = self._populate_gtask(gtask, task)
                self.record_relationship( \
                    local_id = tid, remote_id = gtask_id, \
                    meme = SyncMeme(task.get_modified(),\
                                    self.get_modified_for_task(gtask_id),\
                                    "GTG"))

            elif action == SyncEngine.REMOVE:
                self.datastore.request_task_deletion(tid)
                try:
                    self.sync_engine.break_relationship(local_id = tid)
                    self.save_state()
                except KeyError:
                    pass
                
            elif action == SyncEngine.UPDATE:
                meme = self.sync_engine.get_meme_from_local_id(\
                                                    task.get_id())
                newest = meme.which_is_newest(task.get_modified(),
                                     self.get_modified_for_task(gtask_id))
                if newest == "local":
                    # TODO: get the destination list from the gtl_x tag...
                    gtasklist = self.get_tasklist(gtask_id)
                    gtask = self.service.tasks().get(tasklist=gtasklist['id'], task=gtask_id).execute()
                    self._update_gtask(gtask, task)
                    meme.set_local_last_modified(task.get_modified())
                    meme.set_remote_last_modified(\
                                        self.get_modified_for_task(gtask_id))
                    self.save_state()
            
            elif action == SyncEngine.LOST_SYNCABILITY:
                self._exec_lost_syncability(tid, note)




    ###############################################################################
    ### Helper methods ############################################################
    ###############################################################################
    
    
    
    @interruptible
    def on_gtask_saved(self, gtask):
        '''
        Callback, executed when a Google task is saved by Google Tasks itself
        Updates the related GTG task (or creates one, if necessary).

        @param gtask: the id of the Google Taskk
        '''
        self.cancellation_point()

        @interruptible
        def _execute_on_gtask_saved(self, gtask):
            self.cancellation_point()
            self._process_gtask(gtask)
            self.save_state()

    
    def _time_gtask_to_date(self, string):
        string = string.split('T')[0]

        return string
    
    def get_clean_tag_from_title(self, title):
        Log.debug("[ii] replacing list title " + title)
        return title.replace(' ', '_')
        
    def set_gtasklist_by_tags(self, args):
        """
        Just holding the code for now.
        eventually, this will examine the list tag of a task and move the task to a new list if necessary...
        """
        gtasklist=self.get_tasklist(gtask['id'])
        hasvalidtag = False
        haslisttag = False
        listtag = None
        for t in task.tags:
            Log.debug("[ii] " + task.title + " has tag " + t)
            if ('@gtl_' in t) or ('gtl_' in t):
                if 'Not_Stored' in t:
                    task.remove_tag(t)
                else:
                    haslisttag = True
                    listtag = t
                    targetlist = t.replace('@gtl_', '')
                    if (targetlist != gtasklist['title']) and (targetlist.replace('_', ' ') != gtasklist['title']):
                        Log.debug("[ii] looking for tasklist that matches tag " + t)
                        hasvalidtag = False
                        tasklists=self.service.tasklists().list().execute()
                        for tasklist in tasklists['items']:
                            if (targetlist == tasklist['title']) or (targetlist.replace('_', ' ') == tasklist['title']):
                                #
                                #result = service.tasks().move(tasklist=tasklist['id'], task = gtask['id']).execute()
                                #
                                hasvalidtag = True
                                gtasklist['id'] = tasklist['id']
                                task.set_attribute('gtasklistTitle', tasklist['title'])
                                task.set_attribute('gtasklistID', tasklist['id'])
                                task.set_attribute('gtasklistDeftag', t)
                    
        if (haslisttag is False) or (hasvalidtag is False):
            if listtag is not None:
                task.remove_tag(listtag)
            listtag = '@gtl_' + self.get_clean_tag_from_title(gtasklist['title'])
            task.add_tag(listtag)
    
    def _google_task_is_syncable(self, gtask):
        '''
        Returns True if this Google Task should be synced into GTG tasks.

        @param gtask: the google task id
        @returns Boolean
        '''
        return True

    def _google_task_exists(self, gtaskID):
        '''
        Returns True if  a calendar exists with the given id.

        @param gtask: the Google Task id
        @returns Boolean
        @param gtasklist: a Google tasklist id
        '''
        #print "\n_google_task_exists\n"
        gtasklist=self.get_tasklist(gtaskID)
        if gtasklist is None:
            Log.debug("[ii] Google task not found in any lists : " + gtaskID)
            return False
        try:        
            self.service.tasks().get(tasklist=gtasklist['id'], task=gtaskID).execute()
            return True
        except:
            return False

    def get_modified_for_task(self, gtask):
        '''
        Returns the modification time for the given google task id.

        @param gtask: the google task id
        @returns datetime.datetime
        @param gtasklist: a Google tasklist id
        '''
        gtasklist=self.get_tasklist(gtask)
        #try:
        gtask_instance = self.service.tasks().get(tasklist=gtasklist['id'], task=gtask).execute()
        #except:
         #   pass
        if 'updated' in gtask_instance:
            modified_time = datetime.datetime.strptime(gtask_instance['updated'], "%Y-%m-%dT%H:%M:%S.%fZ" )
        else:
            modified_time = "1970-01-01T00:00:00.000"
        return modified_time

    def _populate_task(self, task, gtaskID, gtasklist=None):
        '''
        Copies the content of a Google task into a GTG task.

        @param task: a GTG Task
        @param gtaskID: a Google Task id
        @param gtasklist: a Google tasklist
        '''
        
        if gtasklist is None:
            gtasklist=self.get_tasklist(gtaskID)
       
        gtask_instance = self.service.tasks().get(tasklist=gtasklist['id'], task=gtaskID).execute()
        try:
            text = gtask_instance['notes']
        except:
            text = ' '
        if text == None :
            text = ' '
        #update the tags list
        
        
        
        #task.set_only_these_tags(extract_tags_from_text(text))
        title = gtask_instance['title']
        task.set_title(title)
        

        # Status: If the task is active in Google, mark it as active in GTG.
        #         If the task is completed in Google, in GTG it can be either
        #           dismissed or done.
        gtg_status = task.get_status()
        google_status = gtask_instance['status']
        if google_status == "needsAction":
            task.set_status(Task.STA_ACTIVE)
        elif google_status == "completed" and gtg_status == Task.STA_ACTIVE:
            task.set_status(Task.STA_DONE)

        #
        # Set attributes with google data...
        #
        task.set_attribute('gtasklistTitle', gtasklist['title'])
        task.set_attribute('gtasklistID', gtasklist['id'])
        tasklisttag = '@gtl_' + self.get_clean_tag_from_title(gtasklist['title'])
        task.set_attribute('gtasklistDeftag', tasklisttag)
        
        task.set_attribute('gtaskID', gtask_instance['id'])
        
        task.set_attribute('getag', gtask_instance['etag'])
        # task.set_attribute('gparent', gtask['parent'])
        task.set_attribute('gposition', gtask_instance['position'])
        # task.set_attribute('gcompleted', gtask['completed'])
        # if 'deleted' in gtask:
        #    task.set_attribute('gdeleted', gtask['deleted'])

        #=======================================================================
        if 'hidden' in gtask_instance:
            task.set_attribute('ghidden', gtask_instance['hidden'])
        #=======================================================================

        if 'completed' in gtask_instance:
            task.set_closed_date(self._time_gtask_to_date(gtask_instance['completed']))
        if 'parent' in gtask_instance:
            task.set_attribute('gparent', gtask_instance['parent'])
            # FIXME: crude shot at setting parents...
            # Try to assign the local ID from the gtask parent ID attribute...
            try:
                task.set_parent(self.sync_engine.get_local_id(gtask_instance['parent']))
            except Exception, e:
                Log.error(e)
            
        if 'due' in gtask_instance:
            Log.debug("[ii] setting local due date to " + gtask_instance['due'] + " for task " + gtask_instance['id'])
            task.set_due_date(self._time_gtask_to_date(gtask_instance['due']))   
            
        for t in task.tags:
            Log.debug("[ii] " + task.title + " has tag " + t)
            if ('@gtl_' in t) or ('gtl_' in t):
                task.remove_tag(t)
                
        for word in text.split():
            if (word.startswith('@gtl_')) or (word.startswith('gtl_')):
                if word != '@gtl_' + self.get_clean_tag_from_title(gtasklist['title']):
                    word = ''
        
        task.set_text(text)
        
        task.add_tag(tasklisttag)
          
            
       
        task.add_remote_id(self.get_id(), gtaskID)

    def _populate_gtask(self, gtask, task):
        '''
        Copies the content of a task into a Google Task.

        @param gtask: a Google Task (the whole thing...)
        @param task: a GTG Task (the whole thing...)
        '''
       
        title = task.get_title()
        
        
        
        # print dir(task.get_remote_ids())
        # print task.get_remote_ids().values()
        # print task.get_remote_ids().values[0]
        

        gtask = {
                'title': title
        }
     
        #start_time = task.get_start_date().to_py_date().strftime('%Y-%m-%dT%H:%M:%S.000Z' )
        due = task.get_due_date()
        if due != Date.no_date():
            gtask['due'] = due.strftime('%Y-%m-%dT%H:%M:%S.000Z' )
    
        
        

        if task.get_status() == Task.STA_ACTIVE:
            gtask['status'] = "needsAction"
        else:
            gtask['status'] = "completed"
            
            
        #
        # deal with tasklist (tag?)
        #
        
        #
        # At this point, we are creating a new ggl task. There should be NO matching task on google...
        # 
        
        Log.debug("[ii] trying to determine task list for task " + title)
        
        gtasklist = {'id':'@default','title':'Default List'}
        hasvalidtag = False
        haslisttag = False
        listtag = None
        listsetbytag = False
        for t in task.tags:
            Log.debug("[ii] " + task.title + " has tag " + t)
            if ('@gtl_' in t) or ('gtl_' in t):
                if listsetbytag is True:
                    task.remove_tag(t)
                elif 'Not_Stored' in t:
                    task.remove_tag(t)
                else:
                    haslisttag = True
                    listtag = t
                    targetlist = t.replace('@gtl_', '')
                    if (targetlist != gtasklist['title']) and (targetlist.replace('_', ' ') != gtasklist['title']):
                        Log.debug("[ii] looking for tasklist that matches tag " + t)
                        hasvalidtag = False
                        tasklists=self.service.tasklists().list().execute()
                        for tasklist in tasklists['items']:
                            if (targetlist == tasklist['title']) or (targetlist.replace('_', ' ') == tasklist['title']):
                                listsetbytag = True
                                hasvalidtag = True
                                gtasklist['id'] = tasklist['id']
                                gtasklist['title'] = tasklist['title']
                                task.set_attribute('gtasklistTitle', tasklist['title'])
                                task.set_attribute('gtasklistID', tasklist['id'])
                                task.set_attribute('gtasklistDeftag', t)
                    
        if (haslisttag is False) or (hasvalidtag is False):
            if listtag is not None:
                task.remove_tag(listtag)
            listtag = '@gtl_' + self.get_clean_tag_from_title(gtasklist['title'])
            task.add_tag(listtag)                        
                        
                        
        #
        # TODO: Do we need to strip the subtasks and check them with ggl?
        #
        content = task.get_excerpt(strip_subtasks=False)               
        
        gtask['notes'] = content,              
                        
                        
            
        result = self.service.tasks().insert(tasklist = gtasklist['id'], body = gtask).execute()
        try: 
            task.set_attribute('gtaskID', result['id'])

            task.set_attribute('getag', result['etag'])
            
            task.set_attribute('gposition', result['position'])
        except:
            Log.debug("[ww] Failed to bind new gtask back to task")
        
        return result['id']
    
    def _update_gtask(self, gtask, task):
        '''
        Updates the content of a Google task if some change is made in the GTG Task.

        @param gtask: a Google Task (the whole thing - should already exist)...
        @param task: a GTG Task (the whole thing too)...
        '''
        # FUTURE: Should try to set/update the parent if it moves in gtg...
        
        #print "\n_update_gtask\n"
        title = task.get_title()
        
     
        #start_time = task.get_start_date().to_py_date().strftime('%Y-%m-%dT%H:%M:%S.000Z' )
        due = task.get_due_date()
        if due != Date.no_date():
            gtask['due'] = due.strftime('%Y-%m-%dT%H:%M:%S.000Z' )
    
        gtask['title'] = title
        
        
        
        gtasklist=self.get_tasklist(gtask['id'])
        listtag = '@gtl_' + self.get_clean_tag_from_title(gtasklist['title'])
        
        for t in task.tags:
            Log.debug("[ii] Update gtask : " + task.title + " has tag " + t)
            if ('@gtl_' in t) or ('gtl_' in t):
                Log.debug("[ii] removing tasklist tag " + t + " from task " + task.title)
                task.remove_tag(t)
                 
        task.add_tag(listtag)
        Log.debug("[ii] Update gtask : checking task text for bad list tags in task " + task.title)
        content = task.get_excerpt(strip_subtasks=False)
        for word in content.split():
            if (word.startswith('@gtl_')) or (word.startswith('gtl_')):
                if word != '@gtl_' + self.get_clean_tag_from_title(gtasklist['title']):
                    Log.debug("[ii] Update gtask : trying to get rid of tag text " + word + " in task  " + task.title)
                    word = ''
        
        
        
        
        gtask['notes'] = content 

        
        
        result = self.service.tasks().update(tasklist = gtasklist['id'], task = gtask['id'], body = gtask).execute()
        
        
        
    def _exec_lost_syncability(self, tid, gtask):
        '''
        Executed when a relationship between tasks loses its syncability
        property. See SyncEngine for an explanation of that.
        This function finds out which object (task/note) is the original one
        and which is the copy, and deletes the copy.

        @param tid: a GTG task tid
        @param gtask: a Google task id
        '''
        #print "\n _exec_lost_syncability\n"
        self.cancellation_point()
        meme = self.sync_engine.get_meme_from_remote_id(gtask)
        #First of all, the relationship is lost
        self.sync_engine.break_relationship(remote_id = gtask)
        if meme.get_origin() == "GTG":
            gtasklist=self.get_tasklist(gtaskID)
            self.service.tasks().delete(tasklist=gtasklist['id'], task=gtask).execute()
            
        else:
            self.datastore.request_task_deletion(tid)

    def break_relationship(self, *args, **kwargs):
        '''
        Proxy method for SyncEngine.break_relationship, which also saves the
        state of the synchronization.
        '''
        try:
            self.sync_engine.break_relationship(*args, **kwargs)
            #we try to save the state at each change in the sync_engine:
            #it's slower, but it should avoid widespread task
            #duplication
            self.save_state()
        except KeyError:
            pass

    def record_relationship(self, *args, **kwargs):
        '''
        Proxy method for SyncEngine.break_relationship, which also saves the
        state of the synchronization.
        '''
        
        self.sync_engine.record_relationship(*args, **kwargs)
        #we try to save the state at each change in the sync_engine:
        #it's slower, but it should avoid widespread task
        #duplication
        self.save_state()
