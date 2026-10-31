import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import export_kaishi_catalog as catalog


class KaishiCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "collection.anki2"
        c = sqlite3.connect(self.db)
        c.executescript('''CREATE TABLE decks(id INTEGER,name TEXT);
            CREATE TABLE fields(ntid INTEGER,ord INTEGER,name TEXT);
            CREATE TABLE notes(id INTEGER,mid INTEGER,flds TEXT);
            CREATE TABLE cards(id INTEGER,nid INTEGER,ord INTEGER,type INTEGER,queue INTEGER,ivl INTEGER,did INTEGER,odid INTEGER);
            CREATE TABLE revlog(id INTEGER,cid INTEGER,type INTEGER,ease INTEGER);''')
        c.executemany('INSERT INTO decks VALUES (?,?)', [(1,'日本語\x1fKaishi 1.5k'),(2,'Other')])
        c.executemany('INSERT INTO fields VALUES (1,?,?)', enumerate(catalog.FIELDS))
        for i in range(1,1502):
            c.execute('INSERT INTO notes VALUES (?,1,?)',(i,'\x1f'.join(['same','かな','meaning','exact sentence','translation'])))
            c.execute('INSERT INTO cards VALUES (?,?,0,?,?,21,?,0)',(i,i,2 if i<=175 else 0,2 if i<=175 else 0,1 if i<=1500 else 2))
            if i<=175:c.execute('INSERT INTO revlog VALUES (?, ?, 1, 3)',(i,i))
        c.commit();c.close()

    def tearDown(self): self.temp.cleanup()

    def test_one_to_one_order_blocks_eligibility_and_no_other_deck(self):
        before = self.db.read_bytes()
        data = catalog.build_catalog(self.db)
        self.assertEqual(data['card_count'],1500)
        self.assertEqual([c['card_id'] for c in data['cards']],list(range(1,1501)))
        self.assertEqual(data['eligible_card_count'],175)
        self.assertEqual([c['ordinal'] for c in data['cards']],list(range(1,1501)))
        self.assertEqual(len(data['blocks']),15)
        self.assertTrue(data['blocks'][0]['all_cards_eligible'])
        self.assertFalse(data['blocks'][1]['all_cards_eligible'])
        self.assertEqual(data['blocks'][1]['eligible_count'],75)
        self.assertEqual(data['blocks'][1]['previous_test_required'],1)
        self.assertEqual(data['cards'][100]['test_number'],2)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertNotIn('review_history',data['cards'][0])
        self.assertNotIn('media',data['cards'][0])

    def test_latest_failed_review_disqualifies_card(self):
        c=sqlite3.connect(self.db);c.execute('INSERT INTO revlog VALUES (99999,1,1,1)');c.commit();c.close()
        self.assertEqual(catalog.build_catalog(self.db)['eligible_card_count'],174)

    def test_sidecar_and_missing_content_fail_closed(self):
        sidecar=Path(str(self.db)+'-wal');sidecar.write_bytes(b'active')
        with self.assertRaises(RuntimeError):catalog.build_catalog(self.db)
        sidecar.unlink()
        c=sqlite3.connect(self.db);c.execute("UPDATE notes SET flds='' WHERE id=1");c.commit();c.close()
        with self.assertRaises(RuntimeError):catalog.build_catalog(self.db)

    def test_separate_manifest_and_existing_export_preserved(self):
        out=self.root/'output';out.mkdir()
        for name in ('card-index.json','cards-0001.json','voice-corpus.txt','manifest.json'):
            (out/name).write_bytes(b'existing tutor bytes')
        with patch('sys.argv',['export','--profile',str(self.root),'--output',str(out)]):catalog.main()
        for name in ('card-index.json','cards-0001.json','voice-corpus.txt','manifest.json'):
            self.assertEqual((out/name).read_bytes(),b'existing tutor bytes')
        manifest=json.loads((out/'kaishi-game-manifest.json').read_text())
        content=(out/manifest['file']).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(),manifest['sha256'])
        self.assertEqual(len(content),manifest['bytes'])
