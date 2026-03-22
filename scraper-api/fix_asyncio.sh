#!/bin/bash
set -e
APP=/workspace/scraper-api/app.py
cp $APP $APP.bak_asyncio_$(date +%Y%m%d_%H%M%S)
python3 -c "
path='/workspace/scraper-api/app.py'
txt=open(path).read()
old='        results, errors, fatal = asyncio.run(run())'
new='        loop = asyncio.new_event_loop()\n        asyncio.set_event_loop(loop)\n        try:\n            results, errors, fatal = loop.run_until_complete(run())\n        finally:\n            loop.close()'
if old not in txt:
    print('ERREUR ancre introuvable'); exit(1)
txt=txt.replace(old,new,1)
open(path,'w').write(txt)
print('OK')
"
python3 -c "import ast; ast.parse(open('$APP').read())" && echo "Syntaxe OK"
pkill -f 'python app.py' 2>/dev/null || true
sleep 1
python /workspace/scraper-api/app.py > /tmp/scraper.log 2>&1 &
sleep 2
echo "Redemarré"
