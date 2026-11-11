"""Generate explicitly fictional, text-based PDFs; no LLM calls."""
import json
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
ROOT=Path(__file__).resolve().parent
DOCS={
'incidents':[
('1. Qualification','Un incident P1 correspond à une indisponibilité totale du service fictif Orion. Le pilote ouvre un ticket INC et note l’heure de début.'),
('2. Première escalade','Pour un incident P1, contacter le responsable d’astreinte. Sans réponse après 10 minutes, appliquer la procédure astreintes, section Relais.'),
('3. Communication','Le pilote publie un point de situation toutes les 30 minutes. Il ne communique aucune donnée client.'),
('4. Clôture','Clôturer après confirmation du rétablissement par le pilote. Conserver les heures de début et de fin et la chronologie des actions.')],
'astreintes':[
('1. Organisation','Le responsable d’astreinte assure la coordination opérationnelle. Les coordonnées personnelles ne figurent pas dans ce document fictif.'),
('2. Relais','Si le responsable d’astreinte ne répond pas après 10 minutes pour un incident P1, contacter le coordinateur de crise. Exception : pendant un exercice, contacter uniquement l’animateur de l’exercice.'),
('3. Passation','La passation a lieu à 09 h. Le sortant transmet les incidents ouverts et les actions en attente.'),
('4. Exercices','Un exercice porte explicitement la mention EXERCICE dans le ticket. Aucune équipe réelle ne doit être mobilisée pour le présent corpus.')],
'changements':[
('1. Demande','Une demande de changement décrit le service, le risque, le plan de retour arrière et le responsable.'),
('2. Validation','Un changement normal nécessite la validation du responsable de service avant exécution. Le demandeur ne peut pas approuver sa propre demande.'),
('3. Urgence','Un changement urgent nécessite une validation du coordinateur de crise. Le motif d’urgence doit être consigné dans le ticket.'),
('4. Retour arrière','Si le contrôle de santé échoue après un changement, appliquer le plan de retour arrière et informer le responsable de service.')]
}
def main():
 (ROOT/'data').mkdir(exist_ok=True)
 for name,pages in DOCS.items():
  c=canvas.Canvas(str(ROOT/'data'/f'{name}.pdf'),pagesize=(595,842))
  c.setTitle(f'FICTIF - {name}')
  for i,(title,body) in enumerate(pages,1):
   c.setFillColorRGB(.05,.16,.25);c.rect(0,740,595,102,fill=1,stroke=0)
   c.setFillColorRGB(1,1,1);c.setFont('Helvetica-Bold',20);c.drawString(42,785,name.upper())
   c.setFont('Helvetica',10);c.drawString(42,761,'CORPUS FICTIF - Démonstrateur PageIndex - aucune règle réelle')
   c.setFillColorRGB(.05,.16,.25);c.setFont('Helvetica-Bold',17);c.drawString(42,695,title)
   c.bookmarkPage(f'p{i}');c.addOutlineEntry(title,f'p{i}',0)
   c.setFont('Helvetica',12)
   for n,line in enumerate(simpleSplit(body,'Helvetica',12,505)):c.drawString(42,650-20*n,line)
   c.setFont('Helvetica',10);c.drawString(42,40,f'{name}.pdf | Page {i} / {len(pages)} | Version fictive 1.0');c.showPage()
  c.save()
 (ROOT/'data'/'corpus.json').write_text(json.dumps(DOCS,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
