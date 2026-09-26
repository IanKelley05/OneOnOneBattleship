import os
import tempfile
import unittest
from datetime import date, timedelta

storage = tempfile.TemporaryDirectory()
os.environ['BATTLESHIP_DATA'] = storage.name
from app import app, db


class GameTest(unittest.TestCase):
    def test_complete_game(self):
        client = app.test_client()
        client.get('/')
        with client.session_transaction() as session:
            token = session['csrf']
        def post(path, data):
            return client.post(path, json=data, headers={'X-CSRF-Token': token})
        fleet = [list(range(5)), list(range(8,12)), list(range(16,19)), list(range(24,27)), [32,40]]
        self.assertEqual(client.get('/api/fleet/South').status_code,403)
        self.assertEqual(client.post('/api/login',json={'password':'testpassword'}).status_code,403)
        self.assertEqual(post('/api/login',{'password':'testpassword'}).status_code,200)
        self.assertEqual(post('/api/setup/South',{'ships':[[0]*5]+fleet[1:]}).status_code,400)
        for tower in ['South','North']:
            self.assertEqual(post('/api/setup/'+tower,{'ships':fleet}).status_code,200)
        self.assertEqual(post('/api/schedule',{'south':date.today().isoformat(),'north':(date.today()+timedelta(days=7)).isoformat()}).status_code,200)
        self.assertEqual(post('/api/turn/North',{'name':'RA','color':'#f87171'}).status_code,400)
        self.assertEqual(post('/api/schedule',{'south':(date.today()-timedelta(days=7)).isoformat(),'north':date.today().isoformat()}).status_code,200)
        state=client.get('/api/state/South').json
        self.assertNotIn('ships',state)
        self.assertNotIn('cells',str(state))
        self.assertEqual(post('/api/turn/South',{'name':'Alex','color':'#f87171'}).status_code,200)
        self.assertEqual(post('/api/turn/South',{'name':'Other','color':'#60a5fa'}).status_code,400)
        turn=client.get('/api/state/South').json['turn']['id']
        self.assertTrue(post('/api/shot/South',{'cell':0,'turn':turn}).json['hit'])
        self.assertEqual(post('/api/shot/South',{'cell':0,'turn':turn}).status_code,400)
        self.assertEqual(post('/api/setup/South',{'ships':fleet}).status_code,200)
        self.assertEqual(post('/api/schedule',{'south':date.today().isoformat(),'north':date.today().isoformat()}).status_code,200)
        for cell in [1,2]:
            self.assertEqual(post('/api/shot/South',{'cell':cell,'turn':turn}).status_code,200)
        partial = client.get('/api/state/South').json
        self.assertEqual(partial['sunk_ships'], [])
        self.assertFalse(any(s['sunk'] for s in partial['shots']))
        self.assertEqual(post('/api/shot/South',{'cell':3,'turn':turn}).status_code,400)
        self.assertEqual(post('/api/turn/South',{'name':'Other','color':'#f87171'}).status_code,400)
        for cell in [63]+[c for ship in fleet for c in ship if c>2]:
            state=client.get('/api/state/South').json
            if not state['turn']:
                self.assertEqual(post('/api/turn/South',{'name':'Alex'}).status_code,200)
                state=client.get('/api/state/South').json
            response = post('/api/shot/South',{'cell':cell,'turn':state['turn']['id']})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['sunk'], cell in [ship[-1] for ship in fleet])
            visible = client.get('/api/state/South').json
            hit_cells = {s['cell'] for s in visible['shots'] if s['hit']}
            self.assertEqual([s['cells'] for s in visible['sunk_ships']],
                             [ship for ship in fleet if set(ship) <= hit_cells])
        state=client.get('/api/state/South').json
        self.assertEqual(sum(s['hit'] for s in state['shots']),17)
        self.assertEqual(len(state['shots']),18)
        self.assertIsNone(state['turn'])
        self.assertEqual([s['cell'] for s in state['shots'] if s['sunk']], [4,11,18,26,40])
        self.assertTrue(all(s['created'] for s in state['shots']))
        self.assertEqual([s['id'] for s in state['shots']], sorted(s['id'] for s in state['shots']))
        self.assertEqual(post('/api/turn/South',{'name':'Alex'}).status_code,400)
        fresh=app.test_client()
        self.assertEqual(len(fresh.get('/api/state/South').json['shots']),18)
        self.assertEqual(fresh.get('/api/state/South').json['sunk_ships'], state['sunk_ships'])
        self.assertEqual(fresh.get('/api/state/North').json['sunk_ships'], [])
        self.assertEqual(fresh.get('/api/fleet/South').status_code,403)
        # Moving a fleet updates existing hits and sunk results without losing shots.
        moved = [list(range(48,53))] + fleet[1:]
        self.assertEqual(post('/api/setup/South',{'ships':moved}).status_code,200)
        updated=client.get('/api/state/South').json
        self.assertEqual(len(updated['shots']),18)
        self.assertEqual(sum(s['hit'] for s in updated['shots']),12)
        self.assertEqual(len(updated['sunk_ships']),4)
        self.assertEqual(updated['players'][0]['hits'],12)
        # Independent dates remain editable after play, with atomic validation.
        self.assertEqual(post('/api/schedule',{'south':date.today().isoformat(),'north':'invalid'}).status_code,400)
        self.assertEqual(client.get('/api/state/North').json['tower']['start'],date.today().isoformat())
        self.assertEqual(post('/api/turn/North',{'name':'North RA','color':'#60a5fa'}).status_code,200)
        north_turn=client.get('/api/state/North').json['turn']['id']
        self.assertEqual(post('/api/shot/North',{'cell':0,'turn':north_turn}).status_code,200)
        north_before=client.get('/api/state/North').json
        self.assertEqual(post('/api/reset/South',{}).status_code,400)
        self.assertEqual(len(client.get('/api/state/South').json['shots']),18)
        fresh.get('/')
        with fresh.session_transaction() as guest:
            guest_token=guest['csrf']
        self.assertEqual(fresh.post('/api/reset/South',json={'confirmed':True},headers={'X-CSRF-Token':guest_token}).status_code,403)
        self.assertEqual(post('/api/reset/South',{'confirmed':True}).status_code,200)
        cleared=client.get('/api/state/South').json
        self.assertEqual(cleared['shots'],[])
        self.assertEqual(cleared['players'],[])
        self.assertEqual(cleared['sunk_ships'],[])
        self.assertIsNone(cleared['turn'])
        self.assertEqual(cleared['tower'],updated['tower'])
        self.assertEqual(client.get('/api/fleet/South').json['ships'],moved)
        north_after=client.get('/api/state/North').json
        for key in ['shots','players','turn','tower']:
            self.assertEqual(north_after[key],north_before[key])
        self.assertEqual(post('/api/turn/South',{'name':'New RA','color':'#f87171'}).status_code,200)
        before_password=client.get('/api/state/South').json
        self.assertEqual(post('/api/password',{'current':'wrong','new':'replacement123','confirm':'replacement123'}).status_code,403)
        self.assertEqual(post('/api/password',{'current':'testpassword','new':'short','confirm':'short'}).status_code,400)
        self.assertEqual(post('/api/password',{'current':'testpassword','new':'replacement123','confirm':'mismatch'}).status_code,400)
        self.assertEqual(post('/api/password',{'current':'testpassword','new':'replacement123','confirm':'replacement123'}).status_code,200)
        self.assertEqual(client.get('/api/state/South').json,before_password)
        self.assertEqual(post('/api/logout',{}).status_code,200)
        self.assertEqual(post('/api/password',{'current':'replacement123','new':'anotherpass','confirm':'anotherpass'}).status_code,403)
        self.assertEqual(post('/api/login',{'password':'testpassword'}).status_code,403)
        self.assertEqual(post('/api/login',{'password':'replacement123'}).status_code,200)
        self.assertEqual(post('/api/logout',{}).status_code,200)
        self.assertEqual(client.get('/api/fleet/South').status_code,403)
        with app.app_context():
            self.assertEqual(db().execute('PRAGMA integrity_check').fetchone()[0],'ok')


if __name__ == '__main__':
    unittest.main()
