
CLIENT_ID = '94851023623.apps.googleusercontent.com'
CLIENT_SECRET = 'p6H1UGaDLAJjDaoUbwu0lNJz'




import httplib2
import oauth2 as oauth


import httplib2



"""
auth_uri = flow.step1_get_authorize_url()
# Redirect the user to auth_uri on your platform.

credentials = flow.step2_exchange(code)

http = httplib2.Http()
http = credentials.authorize(http)


"""


import gflags


from apiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.tools import run

FLAGS = gflags.FLAGS

# Set up a Flow object to be used if we need to authenticate. This
# sample uses OAuth 2.0, and we set up the OAuth2WebServerFlow with
# the information it needs to authenticate. Note that it is called
# the Web Server Flow, but it can also handle the flow for native
# applications
# The client_id and client_secret are copied from the API Access tab on
# the Google APIs Console
FLOW = OAuth2WebServerFlow(client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            scope='https://www.googleapis.com/auth/tasks',
            redirect_uri='localhost',
            user_agent='GTG')
# To disable the local server feature, uncomment the following line:
# FLAGS.auth_local_webserver = False

# If the Credentials don't exist or are invalid, run through the native client
# flow. The Storage object will ensure that if successful the good
# Credentials will get written back to a file.
storage = Storage('tasks.dat')
credentials = storage.get()
if credentials is None or credentials.invalid == True:
    credentials = run(FLOW, storage)
#code = credentials.access_token
#print '>>> TOKEN >>> ' + str(credentials.access_token)
credentials = self.flow.step2_exchange(code)
    # credential = self.flow.step2_exchange(code)

self.storage.put(credentials)
credentials.set_store(self.storage)

# Create an httplib2.Http object to handle our HTTP requests and authorize it
# with our good Credentials.
http = httplib2.Http(ca_certs = '/etc/ssl/certs/ca_certs.pem')
http = credentials.authorize(http)

# Build a service object for interacting with the API. Visit
# the Google APIs Console
# to get a developerKey for your own application.
service = build(serviceName='tasks', version='v1', http=http,
       developerKey='AIzaSyAmUlk8_iv-rYDEcJ2NyeC_KVPNkrsGcqU')