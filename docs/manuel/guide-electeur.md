<!-- SPDX-License-Identifier: 0BSD -->

# Guide de l'électeur

Vous êtes inscrit·e sur la liste électorale de la commune et celle-ci vous
invite à une **consultation**. Ce guide explique comment vous inscrire, voter,
et vérifier que votre vote a bien été enregistré.

## En bref

- **La consultation est consultative.** Son résultat **éclaire** la décision du
  conseil municipal, il ne la lie pas. Cette mention figure sur chaque page.
- **Deux façons de voter** : en ligne, ou sur papier à la mairie si vous n'avez
  pas d'accès à internet. On ne peut pas faire les deux.
- **Votre bulletin voté en ligne n'est relié à votre identité par aucune
  donnée** : la plateforme sait que vous avez voté, jamais comment (R-7.4).
- **Le lien reçu par courriel est précieux.** Selon le scrutin, c'est le seul
  moyen de modifier votre vote, et personne — pas même la mairie — ne peut le
  retrouver ni vous en renvoyer un autre.

## 1. Trouver la consultation

La page publique liste les consultations ouvertes et publiées.

> **Figure 1 — Liste publique des consultations.** [Ouvrir la capture](captures/01-site-public-liste.html)

La page d'une consultation ouverte montre les propositions, la date et l'heure
de **clôture**, l'échéance de saisie des bulletins papier si elle diffère, tout
**report de clôture** déjà décidé (avec son motif), et le rappel du caractère
consultatif.

> **Figure 2 — Page publique d'une consultation ouverte.** [Ouvrir la capture](captures/02-site-public-scrutin.html)

Le nombre de votants **n'est pas affiché** pendant le scrutin, sauf si la
configuration le prévoit : publier la participation en cours de vote peut
l'influencer.

## 2. S'inscrire

L'inscription est **propre à un scrutin**. Si vous participez à deux
consultations en même temps, vous vous inscrivez deux fois et recevez deux liens
indépendants.

> **Figure 3 — Formulaire d'inscription.** [Ouvrir la capture](captures/03-inscription-formulaire.html)

Le formulaire demande :

- votre **nom** — le **nom de naissance** ou le **nom d'usage**, les deux sont
  acceptés ;
- vos **prénoms** ;
- votre **date de naissance** ;
- votre **adresse électronique** ;
- une **déclaration sur l'honneur** (case à cocher) attestant que vous êtes
  inscrit·e sur la liste électorale de la commune.

Conseils :

- **Choisissez une adresse que vous seul·e consultez.** La garantie que votre
  lien de vote reste privé repose là-dessus.
- **Une adresse ne sert qu'une fois par scrutin.** Deux personnes qui partagent
  une boîte ne peuvent pas s'inscrire toutes les deux en ligne : l'une d'elles
  vote sur papier à la mairie.
- La date de naissance porte l'essentiel de la vérification ; la comparaison des
  noms est tolérante (casse, accents, traits d'union, particules, ordre des
  prénoms).

### Ce qui se passe ensuite

| Situation | Message | Suite |
|---|---|---|
| Une seule entrée de la liste correspond, et elle donne l'éligibilité | « Un courriel de confirmation vient de vous être envoyé » | ouvrez le lien reçu (§3) |
| Aucune, ou plusieurs, correspondances — ou une date de naissance incertaine | « Votre inscription est mise à l'étude » | la mairie statue ; vous êtes recontacté·e |
| Une seule entrée correspond mais son type de liste ne donne pas voix sur ce scrutin | « Vous n'êtes pas éligible à cette consultation » | — |
| L'entrée de liste ou l'adresse est déjà inscrite | « Nous ne pouvons pas enregistrer cette demande en ligne. Adressez-vous à la mairie. » | contactez la mairie |

> **Figure 4 — Accusé : courriel de confirmation envoyé.** [Ouvrir la capture](captures/04-inscription-confirmee.html)
>
> **Figure 5 — Accusé : inscription mise à l'étude.** [Ouvrir la capture](captures/05-inscription-en-examen.html)

Pour votre protection, le nom trouvé dans la liste **ne vous est jamais réaffiché**
avant que vous ayez confirmé votre adresse : sans cela, le formulaire deviendrait
un moyen de vérifier, à partir d'un nom et d'une date de naissance, qu'une
personne est inscrite.

## 3. Confirmer son adresse et accéder au bulletin

Le courriel de confirmation contient **un lien**. En l'ouvrant, vous prouvez que
l'adresse est la vôtre **et** vous accédez directement à votre bulletin. Le
courriel :

- indique la date de clôture ;
- si le scrutin autorise la modification, précise que **ce lien est le seul
  moyen de modifier votre bulletin**, que personne ne peut le retrouver, et que
  **si vous le perdez, votre vote reste enregistré et compte normalement** — vous
  ne pourrez simplement plus le changer ;
- ne contient **aucun code de suivi** : le code se rapporte à un bulletin, qui
  n'existe pas encore au moment de l'inscription. Il vous est donné **au moment
  du vote**.

**Conservez ce courriel** jusqu'à la clôture.

## 4. Voter

> **Figure 7 — Bulletin : premier vote.** [Ouvrir la capture](captures/07-bulletin-vote.html)

- **L'ordre des propositions est tiré au hasard pour chaque électeur**,
  indépendamment de l'ordre de la configuration.
- Vous classez les propositions selon les règles du scrutin (classement complet
  exigé ou non, ex æquo autorisés ou non). Ces règles sont **vérifiées sur le
  serveur**, pas seulement dans le navigateur.
- Le classement se fait au clavier et au lecteur d'écran : des listes déroulantes
  numérotées (ou des boutons monter/descendre) sont toujours disponibles en
  complément du glisser-déposer.
- Si le scrutin **n'autorise pas** la modification, la page vous le dit **avant**
  la validation : votre bulletin est déposé une seule fois.

Après validation, un **récapitulatif** de votre classement et votre **code de
suivi** s'affichent, et vous les recevez **par courriel**. Conservez le code :
après la clôture, il vous permet de retrouver votre bulletin dans la liste
publiée, **sans révéler votre identité**.

## 5. Modifier son vote (si le scrutin l'autorise)

Rouvrez le **lien reçu lors de l'inscription**. Vous pouvez modifier autant de
fois que vous le souhaitez jusqu'à la clôture.

> **Figure 8 — Bulletin : modification.** [Ouvrir la capture](captures/08-bulletin-modification.html)

- Chaque modification crée une **nouvelle version** ; la précédente est
  conservée mais n'est plus comptée. Votre **code de suivi ne change pas**.
- Aucun nouveau courriel n'est envoyé : le récapitulatif s'affiche à l'écran, et
  le code est celui que vous détenez déjà.
- **Si vous avez perdu le lien**, vous ne pouvez ni le récupérer ni modifier
  votre bulletin — mais **celui-ci reste compté**.

Si vous rouvrez le lien alors que le scrutin n'autorise pas la modification, ou
que vous avez déjà voté sur un scrutin sans modification, un message vous
l'indique.

> **Figure 9 — Message « un bulletin a déjà été enregistré ».** [Ouvrir la capture](captures/09-bulletin-deja-enregistre.html)

## 6. Rappel

48 heures avant la clôture, un **rappel** est envoyé aux personnes inscrites qui
n'ont pas encore voté. Il ne contient pas de nouveau lien : utilisez celui de
votre inscription, ou adressez-vous à la mairie.

## 7. Voter sur papier

Si vous n'avez pas d'accès à internet, présentez-vous à la mairie. Un·e élu·e
enregistre votre bulletin en votre nom après vous avoir identifié·e sur la liste
électorale, et vous remet un **reçu portant votre code de suivi**.

> **Important.** Un bulletin déposé sur **papier reste associé à votre identité**
> dans le système — contrairement à un bulletin voté en ligne — à des fins de
> traçabilité et pour permettre sa suppression à votre demande. Cette
> association est effacée deux mois après la clôture.

Si vous avez déjà voté sur papier, le vote en ligne vous est refusé (adressez-vous
à la mairie pour faire supprimer le bulletin papier au préalable). Si vous avez
déjà voté en ligne, la mairie ne peut pas saisir de bulletin papier à votre
place : le vote en ligne fait foi.

## 8. Vérifier, après la clôture

> **Figure 20 — Page publique de résultats.** [Ouvrir la capture](captures/20-site-public-resultats.html)

Après la publication, la page de la consultation porte :

- la **liste anonymisée des bulletins** (code de suivi + classement), en CSV et
  JSON ;
- la **matrice des préférences deux à deux** et le **raisonnement** menant au
  résultat ;
- le nombre d'inscrits, de bulletins par canal, d'électeurs n'ayant pas voté ;
- la **graine d'ouverture**, le détail d'un éventuel départage, et
  l'**empreinte de clôture**.

Vous pouvez :

1. **retrouver votre code de suivi** dans la liste et vérifier que votre
   classement est celui que vous avez déposé ;
2. **recalculer le résultat** vous-même à partir des données publiées — une
   implémentation indépendante du dépouillement et de l'empreinte est publiée à
   cette fin.

> **À savoir.** Si vous conservez votre code de suivi, vous pouvez retrouver
> votre propre ligne dans le fichier publié et donc prouver à un tiers comment
> vous avez voté. C'est inhérent à une vérifiabilité fondée sur la publication.
> Cette plateforme **ne doit pas être utilisée là où la contrainte ou l'achat de
> voix sont un risque réel**.

## 9. Accessibilité et langues

L'interface est conforme au RGAA, utilisable au téléphone, et disponible en
français ; d'autres langues sont proposées si la consultation les active. Le
français fait foi ; les pages à portée juridique (notices) le rappellent quand
elles sont lues dans une traduction.
