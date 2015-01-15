'''
    This script will attempt to open your webbrowser,
    perform OAuth 2 authentication and print your access token.

    It depends on two libraries: oauth2client and gflags.

    To install dependencies from PyPI:

    $ pip install python-gflags oauth2client

    Then run this script:

    $ python get_oauth2_token.py
    
    This is a combination of snippets from:
    https://developers.google.com/api-client-library/python/guide/aaa_oauth
'''
 
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.tools import run
from oauth2client.file import Storage
 
CLIENT_ID = '94851023623.apps.googleusercontent.com'
CLIENT_SECRET = 'p6H1UGaDLAJjDaoUbwu0lNJz'
 
flow = OAuth2WebServerFlow(client_id=CLIENT_ID,
                           client_secret=CLIENT_SECRET,
                           scope='https://www.googleapis.com/auth/tasks',
                           redirect_uri='http://localhost:8080')
 
storage = Storage('creds.data')
 
credentials = run(flow, storage)
 
print "access_token: %s" % credentials.access_token