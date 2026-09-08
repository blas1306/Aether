import sys
sys.path.insert(0, '/home/blasm/proyectos/Aether/src')
from aether import language_service
source = open('scrap/acbwowic.ae','r',encoding='utf-8').read()
diags = language_service.analyze_source(source, source_root='/home/blasm/proyectos/Aether')
for d in diags:
    print(d.severity, d.line, d.column, d.message)
print('---done---')
