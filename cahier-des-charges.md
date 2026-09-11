# Cahier des charges fonctionnel — Plateforme de scrutins communaux

**Une commune française**
v0.5 — périmètre fonctionnel uniquement ; aucun choix technique. Les règles sont numérotées `R-x.y` et servent de référence à la spécification d'implémentation.

---

## 1. Objet et périmètre

**R-1.1** La plateforme permet à la commune d'organiser des scrutins consultatifs auprès de ses électeurs inscrits, conduits en ligne, avec possibilité de recueillir des bulletins sur support papier saisis par un membre du conseil municipal.

**R-1.2** Rien de ce qui est propre à un scrutin déterminé n'est codé en dur : ni son intitulé, ni ses options, ni ses dates, ni sa méthode de dépouillement. Tout cela relève de la configuration.

**R-1.3** La plateforme est destinée à une seule commune. La gestion multi-collectivités est hors périmètre, sans que la conception ne doive l'interdire pour l'avenir.

**R-1.4** Les scrutins sont consultatifs. La page publique de chaque scrutin énonce expressément que le résultat éclaire la délibération du conseil municipal sans la lier, et que le scrutin ne constitue pas une consultation des électeurs au sens des articles L1112-15 et suivants du CGCT.

**R-1.5** Le logiciel est publié en source ouverte, à raison d'une instance par commune.

---

## 2. Rôles

**R-2.1** Les rôles sont attribués scrutin par scrutin, à l'exception de celui d'administrateur communal.

| Rôle | Habilitations |
|---|---|
| Administrateur communal | Crée les scrutins, attribue les rôles propres à chaque scrutin, importe la liste électorale. Ce rôle n'emporte par lui-même aucun accès aux bulletins. |
| Administrateur de scrutin | Modifie la configuration tant que le scrutin est à l'état de projet ; annonce, ouvre, clôt et publie le scrutin ; statue sur les inscriptions signalées pour examen manuel. |
| Opérateur de saisie (conseiller municipal) | Saisit, rectifie et supprime les bulletins papier du scrutin ; délivre les récépissés. |
| Auditeur | Accès en lecture seule à la configuration du scrutin, à la liste anonymisée des bulletins et à l'intégralité du journal d'audit. |
| Électeur | S'inscrit, exprime et, lorsque le scrutin le permet, modifie son vote ; vérifie l'enregistrement de son propre bulletin. |

**R-2.2** Chaque opérateur dispose d'un compte nominatif personnel. Les comptes partagés sont proscrits par conception : le système impose un compte par personne physique.

**R-2.3** Aucun rôle ne permet d'associer un électeur ayant voté en ligne au bulletin qu'il a exprimé (voir R-7.4).

**R-2.4** L'interface d'administration est développée pour cet usage. Elle est employée par des conseillers municipaux et des agents de la mairie, relève de la règle R-14.1 au même titre que le reste du site, et ne doit pas présenter des actions destructrices à côté des actions courantes.

---

## 3. Objet « scrutin » et cycle de vie

**R-3.1** Un scrutin comporte : un intitulé ; une description ; une liste ordonnée d'au moins deux options ; une date et heure d'ouverture ; une date et heure de clôture ; un fuseau horaire ; une méthode de dépouillement et sa version ; les contraintes de bulletin (classement complet exigé ou non, ex æquo admis ou non) ; une règle de départage ; la faculté ou non pour l'électeur de modifier son bulletin (R-7.1) ; l'affichage ou non de la participation en cours de scrutin (R-11.5) ; les types de liste ouvrant droit de vote (R-4.7) ; les langues activées (R-14.3) ; les exigences de forme applicables aux bulletins papier (R-8.2) ; une copie figée de la liste électorale ; un indicateur de scrutin d'essai ; un état.

**R-3.2** Les changements d'état sont strictement ordonnés : `projet → [annoncé] → ouvert → clos → publié`. L'état `annoncé` est une étape facultative (R-3.10) : un scrutin peut aussi passer directement de `projet` à `ouvert`. Aucune transition n'est réversible.

**R-3.3** La configuration est librement modifiable à l'état de `projet` et devient immuable dès que le scrutin quitte cet état, qu'il passe à `annoncé` ou directement à `ouvert`.

**R-3.4** Seule exception à la règle R-3.3 : la date de clôture peut être prorogée pendant que le scrutin est ouvert. La prorogation est consignée au journal d'audit avec l'identité de l'opérateur, l'horodatage et un motif obligatoire, et elle est affichée sur la page publique du scrutin.

**R-3.5** La clôture à la date et heure fixées est imposée côté serveur. Les bulletins et modifications parvenus postérieurement à cet instant sont refusés.

**R-3.6** Un scrutin peut être créé par duplication de l'intégralité de la configuration d'un scrutin existant (R-3.1), à l'exclusion du corps électoral et des bulletins ; ou à partir d'un modèle nommé (R-3.9), qui ne transmet que la méthode de dépouillement et sa version, les contraintes de bulletin, la règle de départage, les exigences de forme des bulletins papier, la faculté de modifier son bulletin, les types de liste ouvrant droit de vote et les langues activées — l'intitulé, la description et les options du nouveau scrutin restent à saisir.

**R-3.7** Un scrutin marqué comme scrutin d'essai est exclu des listes publiques, des résultats publiés et de toute statistique. Cette qualité est fixée à la création et n'est pas modifiable.

**R-3.8** Plusieurs scrutins peuvent se dérouler simultanément auprès du même corps électoral. Chacun est indépendant à tous égards : inscription distincte, copie figée distincte de la liste électorale, jetons distincts, bulletins distincts.

**R-3.9** Un scrutin, à quelque état qu'il soit, peut être enregistré comme modèle nommé, reprenant les mêmes éléments qu'un modèle transmet à la création (R-3.6). Un modèle n'est pas un scrutin : il n'a ni intitulé, ni description, ni options, ni dates, ni corps électoral, ni bulletins, et n'est soumis à aucun cycle de vie ; seul son nom, choisi par l'opérateur, l'identifie.

**R-3.10** À l'option de l'administrateur de scrutin, un scrutin encore à l'état de projet peut être annoncé : il passe alors à l'état `annoncé`, visible sur le site public avant son ouverture. Les propositions et le calendrier y sont montrés, aucune inscription ni aucun vote n'y est proposé, et la page indique expressément que le scrutin n'est pas encore ouvert. Le passage à cet état fige la configuration au même titre que le passage à l'état ouvert (R-3.3) : la page publique ne peut donc pas changer sous les yeux de qui la consulte. Cette étape est facultative ; un scrutin encore à l'état de projet n'apparaît sur aucune page publique.

---

## 4. Corps électoral

**R-4.1** La qualité d'électeur est réservée aux personnes inscrites sur la liste électorale de la commune.

**R-4.2** La liste est importée par l'administrateur communal à partir d'un export `.xlsx` ou `.csv`. Seul le nécessaire est importé : nom de naissance, nom d'usage, prénoms, date de naissance et type de liste. Le sexe, la nationalité, la commune, le département et le pays de naissance, l'adresse, le bureau de vote, la circonscription, le canton et le numéro d'ordre ne sont pas importés, sous réserve de l'adresse lorsque l'inscription par voie postale est mise en œuvre. La nationalité, en particulier, révèle l'origine nationale et se déduit au demeurant du type de liste.

**R-4.3** Lors du passage à l'état `ouvert`, le scrutin constitue une copie figée et immuable de la liste électorale, archivée avec lui. Les modifications ultérieures de la liste sont sans effet sur un scrutin ouvert ou clos.

**R-4.4** La copie figée demeure accessible aux auditeurs après la clôture, afin que la question de savoir qui était admis à voter reste vérifiable ultérieurement. Les données d'identité y sont conservées en clair et non sous forme d'empreinte, ce qu'exigent la file d'examen des inscriptions, la recherche prévue à la règle R-8.3 et la présente règle ; c'est la durée de conservation fixée à la règle R-13.3 qui en borne l'exposition.

**R-4.5** La procédure d'import comporte : la sélection du fichier et la mise en correspondance des colonnes ; un rapport de contrôle préalable ; un aperçu soumis à validation expresse ; et une exécution transactionnelle, l'import étant intégralement appliqué ou intégralement abandonné. L'import est consigné au journal d'audit avec le nom du fichier, son empreinte, le nombre de lignes et l'identité de l'opérateur. Un nouvel import remplace intégralement la liste courante et demeure sans effet sur les scrutins déjà ouverts.

Seul un fichier structurellement inexploitable fait échec à l'import : colonne obligatoire manquante, ou lignes dépourvues de nom. Les doublons, les dates incertaines et les lignes incomplètes sont signalés et importés, s'agissant de faits relatifs à la liste et non de défauts du fichier.

**R-4.6** L'export ne comporte pas une ligne par électeur. L'électeur admis à voter à plusieurs types de scrutins figure une fois par type de liste, avec des données d'identité identiques. L'import fusionne ces lignes en une entrée unique portant un ensemble de types de liste ; à défaut, une même personne dispose de deux entrées et peut s'inscrire deux fois.

**R-4.7** Le droit de vote est filtré par type de liste, selon la configuration du scrutin. Une consultation portant sur une question communale concerne la liste principale et la liste complémentaire municipale ; l'inscription sur la seule liste complémentaire européenne n'y ouvre pas droit.

**R-4.8** Le numéro d'ordre figurant sur la liste n'est ni unique ni stable : il est renuméroté à chaque modification de la liste et ne peut servir de clé.

**R-4.9** Les dates de naissance ne sont pas uniformément bien formées, notamment pour les électeurs nés à l'étranger. Une date qui ne peut être analysée est conservée telle quelle et l'entrée signalée comme incertaine ; une telle entrée est importée normalement, son refus excluant un électeur réel, mais ne fait jamais l'objet d'une correspondance automatique et est toujours renvoyée à la file d'examen.

---

## 5. Inscription

**R-5.1** L'inscription est propre à un scrutin déterminé. Un électeur participant à deux scrutins simultanés s'inscrit deux fois et reçoit deux jetons indépendants. Il s'agit d'une conséquence assumée de la règle R-13.4.

**R-5.2** Le formulaire d'inscription recueille : le nom, les prénoms, la date de naissance, l'adresse de courrier électronique, ainsi qu'une déclaration sur l'honneur, sous forme de case à cocher, d'inscription sur la liste électorale de la commune. Le formulaire admet indifféremment le nom de naissance ou le nom d'usage, et l'indique.

**R-5.3** L'inscription est rapprochée de la copie figée de la liste électorale sur le nom normalisé et la date de naissance. La normalisation porte sur la casse, les signes diacritiques, les traits d'union, les apostrophes, les particules, l'ordre des prénoms, et procède à la comparaison tant avec le nom de naissance qu'avec le nom d'usage. La date de naissance emportant l'essentiel du pouvoir discriminant, la comparaison des noms peut demeurer tolérante.

**R-5.4** Suites données :
- une seule entrée correspondante — l'inscription se poursuit ;
- aucune entrée correspondante, plusieurs entrées correspondantes, ou une entrée signalée comme incertaine au titre de la règle R-4.9 — l'inscription est mise en attente d'examen manuel ;
- une entrée correspondante dont les types de liste n'ouvrent pas droit de vote au sens de la règle R-4.7 — l'inscription est refusée, le motif étant consigné.

Dans les cas d'examen manuel, l'administrateur accepte ou rejette l'inscription en motivant sa décision. Une inscription acceptée passe à l'état d'attente de confirmation prévu à la règle R-5.5, et jamais directement à l'état actif. L'électeur est informé que son inscription est en cours d'examen.

**R-5.5** L'inscription est confirmée par un lien adressé à l'adresse électronique déclarée. Une inscription non confirmée n'emporte aucun bulletin, ne permet pas de voter et n'est pas décomptée dans la participation.

**R-5.6** Le courriel de confirmation comporte, lorsque le scrutin admet la modification, le lien de modification, lequel cesse d'être opérant à la clôture. Il ne comporte pas de code de suivi : celui-ci se rattache à un bulletin, qui n'existe pas encore au stade de l'inscription, et n'est délivré qu'à l'expression du vote (R-6.4) ou sur le récépissé papier (R-8.4).

**R-5.7** Un rappel est adressé 48 heures avant la clôture aux électeurs inscrits n'ayant pas exprimé de vote.

**R-5.8** Les points d'entrée d'inscription font l'objet d'une limitation du nombre de requêtes.

**R-5.9** Une même entrée de la liste ne peut donner lieu qu'à une seule inscription par scrutin. Toute tentative d'inscription visant une entrée déjà inscrite est refusée, invite l'intéressé à se rapprocher de la mairie, et est consignée au journal d'audit et signalée à l'administrateur de scrutin. Aucun détail de l'inscription existante n'est divulgué.

**R-5.10** Une même adresse électronique ne peut de même donner lieu qu'à une seule inscription par scrutin, l'adresse étant comparée en minuscules et pour le surplus telle qu'elle a été saisie. Aucune normalisation des alias n'est opérée : le traitement des suffixes et des points relève de conventions propres à chaque fournisseur, et toute règle en la matière confondrait des personnes distinctes ou donnerait une assurance trompeuse quant à celles qu'elle laisserait passer. Deux personnes partageant une même boîte aux lettres ne peuvent donc s'inscrire toutes deux en ligne ; leur voie est celle du bulletin papier en mairie.

**R-5.11** À aucun moment, avant confirmation de la boîte aux lettres, l'identité rapprochée n'est restituée à la personne qui s'inscrit, faute de quoi le formulaire deviendrait un moyen de confirmer, à partir d'un nom et d'une date de naissance, qu'une personne est inscrite.

**R-5.12** Les données d'identité figurant sur la liste électorale peuvent être obtenues par tout électeur au titre de l'article L.37 du code électoral. Le rapprochement avec la liste établit donc la qualité d'électeur et non l'identité, et l'assurance procurée par la seule inscription en ligne s'en trouve limitée d'autant.

---

## 6. Bulletin

**R-6.1** Le bulletin présente les options du scrutin et recueille un classement conforme aux contraintes définies pour ce scrutin. Ces contraintes sont contrôlées côté serveur, et non par le seul navigateur.

**R-6.2** L'ordre d'affichage des options est tiré au hasard pour chaque électeur, indépendamment de l'ordre enregistré dans la configuration.

**R-6.3** L'interface de classement offre une solution de remplacement au glisser-déposer (listes déroulantes numérotées ou équivalent), utilisable au clavier et avec un lecteur d'écran.

**R-6.4** À la première expression du vote, l'électeur se voit présenter un récapitulatif de son classement et son code de suivi, et les reçoit par courrier électronique. Lors d'une modification ultérieure, le récapitulatif est présenté à l'écran ; aucun courriel n'est adressé, le code de suivi étant inchangé (R-7.2) et déjà détenu par l'électeur.

**R-6.5** Lorsque le scrutin n'admet pas la modification, la page du bulletin l'indique avant la validation, et non dans le seul accusé de réception.

---

## 7. Modification et anonymat

**R-7.1** La faculté pour l'électeur de modifier son bulletin est arrêtée pour chaque scrutin. Lorsqu'elle est admise, l'électeur peut modifier son bulletin autant de fois qu'il le souhaite jusqu'à la clôture, au moyen du lien de modification. Dans le cas contraire, le bulletin est exprimé une seule fois et tout usage ultérieur du lien est refusé.

**R-7.2** Toute modification crée une nouvelle version du bulletin. Les versions ne sont jamais écrasées et aucun bulletin n'est jamais matériellement supprimé. Chaque bulletin porte un état distinguant la version en vigueur, les versions périmées, les bulletins retirés par un opérateur au titre de la règle R-8.5 et les saisies en attente de contreseing au titre de la règle R-8.7. Seuls les bulletins en vigueur sont décomptés, couverts par l'empreinte prévue à la règle R-11.1 et publiés au titre de la règle R-11.2.

**R-7.3** L'historique des versions est conservé à des fins d'audit.

**R-7.4** Le lien entre un électeur votant en ligne et son bulletin n'est pas reconstituable à partir de la base de données. Chaque électeur reçoit un jeton aléatoire, communiqué exclusivement dans le courriel de confirmation. L'enregistrement de l'électeur porte `H("voter" ‖ sel ‖ jeton)` ; l'enregistrement du bulletin porte `H("ballot" ‖ sel ‖ jeton)`. Aucune jointure entre les deux tables n'est possible. Seul le détenteur du jeton peut accéder à son propre bulletin.

**R-7.4 bis** Lorsque le scrutin n'admet pas la modification, aucun lien entre le jeton et le bulletin n'est calculé ni conservé : rien ne rattache alors un bulletin au jeton qui l'a exprimé, et le code de suivi de l'électeur en constitue l'unique repère. Le scrutin recherchant l'approche la plus étroite du secret du vote écarte la modification.

**R-7.4 ter** Le jeton circule dans un lien hypertexte. Le système l'échange en conséquence, dès le premier usage, contre une session, redirige vers une adresse qui ne le contient pas, supprime la journalisation de ces adresses et prescrit aux navigateurs de ne transmettre aucun référent. À défaut de ces mesures, l'engagement énoncé à la règle R-7.4 n'est pas tenu.

**R-7.5** Les administrateurs ne disposent en conséquence que de deux listes inconciliables : les noms assortis d'un indicateur « a voté / n'a pas voté », et les classements anonymes identifiés par leur code de suivi.

**R-7.6** Lorsque la modification est admise, l'électeur qui perd son jeton ne peut ni le recouvrer ni modifier son bulletin. Le courriel de confirmation le mentionne expressément. Le bulletin demeure décompté.

---

## 8. Bulletins papier

**R-8.1** Un opérateur de saisie peut enregistrer un bulletin pour le compte d'un électeur dépourvu d'accès à internet.

**R-8.2** Les exigences de forme applicables à cette voie de vote sont arrêtées scrutin par scrutin, parmi les options suivantes : recueil d'un formulaire papier signé ; contreseing d'un second opérateur ; rapprochement formalisé à la clôture. Aucune n'est activée par défaut. Demeurent en revanche applicables en toute hypothèse les règles R-8.3 à R-8.5, qui constituent le socle minimal de traçabilité.

**R-8.2 bis** Lorsque le formulaire papier signé est exigé, il comprend le classement, la déclaration sur l'honneur et l'identité de l'électeur, ainsi qu'une mention indiquant qu'un bulletin saisi par cette voie demeure associé à l'identité de l'électeur dans le système — à la différence d'un bulletin exprimé en ligne — aux fins de traçabilité et de suppression ultérieure éventuelle à sa demande. En l'absence de formulaire, cette information est portée sur le récépissé prévu à la règle R-8.4.

**R-8.3** Avant de créer le bulletin, l'opérateur effectue une recherche dans la copie figée de la liste électorale et se voit présenter les correspondances approchantes pour confirmation. Lorsque deux entrées ne peuvent être distinguées au vu des données conservées, l'opérateur tranche avec l'électeur présent, et non à partir de l'enregistrement.

**R-8.4** La saisie donne lieu à l'impression d'un récépissé portant le code de suivi, remis à l'électeur.

**R-8.5** La rectification et la suppression d'un bulletin papier sont ouvertes à l'opérateur, chacune exigeant un motif obligatoire et donnant lieu à une inscription au journal d'audit mentionnant l'opérateur, l'horodatage et l'état antérieur et postérieur. La rectification demeure ouverte que le scrutin admette ou non la modification par l'électeur : la réparation d'une erreur de saisie n'est pas le même acte qu'un changement d'avis.

**R-8.6** Lorsque le rapprochement formalisé est exigé par la configuration, les formulaires papier sont conservés par la commune et rapprochés des bulletins enregistrés lors de la clôture, le procès-verbal de rapprochement étant signé et archivé. À défaut, le journal d'audit tient lieu de trace.

**R-8.7** Le contreseing d'un second opérateur constitue une option de configuration, désactivée par défaut. Lorsqu'elle est activée, la saisie n'est réputée définitive, et le bulletin n'est décompté, qu'après validation par un second opérateur nommément identifié.

**R-8.7 bis** La clôture est refusée tant qu'une saisie demeure en attente de contreseing. L'administrateur de scrutin fait procéder aux contreseings ou passe outre en énonçant un motif obligatoire, lequel est consigné et figure dans la publication. Les saisies non contresignées ne sont pas décomptées, l'abandon silencieux de bulletins à la clôture n'étant pas admis.

---

## 9. Concours des deux voies de vote

**R-9.1** L'enregistrement de chaque électeur porte un indicateur de voie de vote : aucune, en ligne, ou papier.

**R-9.2** Bulletin papier déjà enregistré → le vote en ligne est refusé, un message invitant l'intéressé à se rendre en mairie pour obtenir au préalable la suppression de son bulletin papier.

**R-9.3** Bulletin en ligne déjà enregistré → la saisie d'un bulletin papier est refusée. Un bulletin exprimé en ligne est anonyme et ne peut être localisé à partir de l'enregistrement de l'électeur (R-7.4) ; il ne peut donc être remplacé. Lorsque le scrutin admet la modification, l'électeur est invité à modifier lui-même son bulletin en ligne ; à défaut, l'écran indique que le vote en ligne est définitif.

**R-9.4** La suppression d'un bulletin papier par un opérateur efface l'indicateur et rouvre le vote en ligne pour l'électeur concerné.

---

## 10. Dépouillement

**R-10.1** Le dépouillement constitue une fonction pure : ensemble des bulletins en vigueur + méthode + paramètres → vainqueur, résultats intermédiaires et exposé du raisonnement en clair.

**R-10.2** L'identifiant de la méthode et sa version sont enregistrés avec le scrutin, de sorte qu'un résultat publié demeure reproductible nonobstant les évolutions ultérieures du code.

**R-10.3** Méthodes disponibles dès la première version : méthode de Schulze, vote à choix unique (pluralité), vote par approbation.

**R-10.4** Lorsque la configuration du scrutin n'exige pas un classement complet, la méthode de Schulze traite les options non classées comme ex æquo au dernier rang.

**R-10.5** Lorsque la méthode laisse subsister une véritable égalité, la règle de départage propre au scrutin s'applique. Règle par défaut : tirage au sort informatique, aléatoire mais reproductible et vérifiable par tout tiers, opéré comme suit :

1. une graine aléatoire est tirée et publiée lors de l'ouverture du scrutin, où elle devient immuable au titre de la règle R-3.3 ;
2. la graine de départage est égale à `H(graine d'ouverture ‖ empreinte de clôture)`, l'empreinte de clôture étant celle définie à la règle R-11.1 ;
3. les options à départager sont ordonnées par valeur croissante de `H(graine de départage ‖ identifiant de l'option)`, la première l'emportant.

Aucun générateur pseudo-aléatoire de bibliothèque n'est employé, la reproductibilité ne devant dépendre ni du langage ni de la plateforme d'exécution. La graine d'ouverture, l'empreinte de clôture et le détail du calcul sont publiés avec le résultat.

**R-10.5 bis** Le procédé décrit à la règle R-10.5 garantit que l'issue du départage n'est ni prévisible avant la clôture ni influençable par l'organisateur, la graine de départage dépendant de l'ensemble des bulletins exprimés. La configuration du scrutin peut néanmoins lui substituer un tirage au sort physique opéré publiquement, dont le résultat est consigné dans la publication.

**R-10.6** Le dépouillement n'est effectué qu'après la clôture. Il ne lit que les bulletins, jamais le registre des électeurs.

**R-10.7** Le dépouillement repose sur les identifiants des options et jamais sur leurs libellés ; le résultat et l'empreinte prévue à la règle R-11.1 sont ainsi indépendants des libellés et de leurs traductions. Les libellés sont figés avec le reste de la configuration au passage à l'état `ouvert` (règle R-3.3), de sorte que le résultat publié présente exactement les libellés que les électeurs ont classés.

---

## 11. Publication et vérifiabilité

**R-11.1** À la clôture, le système calcule et affiche une empreinte cryptographique portant sur l'ensemble des bulletins en vigueur, préalablement à la publication du résultat. La sérialisation retenue est documentée, afin que l'empreinte puisse être recalculée à partir des seules données publiées.

**R-11.2** La publication comprend : la liste anonymisée des bulletins (code de suivi et classement) aux formats CSV et JSON ; la matrice des duels ; l'exposé du raisonnement conduisant au résultat ; le nombre d'électeurs inscrits, le nombre de bulletins exprimés par chacune des deux voies et le nombre d'électeurs n'ayant pas voté ; la graine d'ouverture et le détail d'un éventuel départage ; ainsi que l'empreinte de clôture. La liste publiée comprend les bulletins en vigueur et rien d'autre.

**R-11.3** Lorsque le nombre d'options est réduit, un tableau récapitulatif indiquant le nombre de bulletins pour chaque ordre distinct est publié en outre. Pour trois options intégralement classées, ce tableau comporte six lignes et permet à lui seul de recalculer le résultat.

**R-11.4** Tout électeur peut retrouver son code de suivi dans la liste publiée et vérifier que son bulletin a été enregistré tel qu'il l'a exprimé. Tout tiers peut recalculer le résultat à partir des données publiées. Une implémentation indépendante du dépouillement et de l'empreinte est publiée à cette fin.

**R-11.5** La participation n'est affichée en cours de scrutin que si la configuration le prévoit ; à défaut, elle ne l'est pas, la publication du taux de participation pendant le scrutin étant de nature à l'influencer. Lorsqu'elle n'est pas affichée, aucune page ni interface ne divulgue de décompte en cours. La participation n'est en aucun cas publiée par bureau de vote.

---

## 12. Journal d'audit

**R-12.1** Le journal est en ajout seul et consigne au minimum : les modifications de la configuration des scrutins ; les changements d'état et les prorogations de la date de clôture ; les imports et les copies figées de la liste électorale ; les décisions rendues sur les inscriptions soumises à examen ; les tentatives d'inscription refusées ; la création, la rectification et la suppression des bulletins papier ; les contreseings et les passer-outre à la clôture ; les passages outre l'avertissement de concours des voies de vote ; les attributions de rôles ; et les accès au journal lui-même.

**R-12.2** Chaque inscription mentionne l'opérateur, l'horodatage, l'objet concerné, l'état antérieur et postérieur, ainsi que le motif lorsqu'il est exigé.

**R-12.3** Les auditeurs disposent d'un accès en lecture à l'intégralité du journal. Aucun rôle ne permet de modifier ni de supprimer une inscription.

**R-12.4** Chaque catégorie d'inscription déclare celles de ses rubriques qui comportent des données personnelles, afin que la procédure de conservation prévue à la règle R-13.3 puisse effacer précisément ces rubriques en préservant l'inscription, son auteur, sa date et son motif.

---

## 13. Protection des données

**R-13.1** La commune est responsable de traitement. Le traitement est inscrit au registre des traitements.

**R-13.2** Une notice d'information est présentée lors de l'inscription, indiquant la finalité, la base légale, les durées de conservation, les destinataires et les droits des personnes concernées, ainsi que l'identité du référent chargé des demandes et réclamations.

**R-13.3** Durées de conservation : les données d'identité (enregistrements d'inscription, copie figée de la liste électorale, association des bulletins papier aux électeurs) sont supprimées à l'expiration d'un délai de deux mois courant à compter de la clôture du scrutin, et les rubriques déclarées au titre de la règle R-12.4 sont effacées du journal d'audit au même terme. Le point de départ est la clôture et non la publication : un scrutin clos qui n'est jamais publié — départage physique non tranché, résultat abandonné — conserverait sinon ces données indéfiniment. Les bulletins anonymisés, le résultat publié et le journal lui-même sont conservés au-delà.

**R-13.3 bis** La liste électorale importée mais non encore figée dans un scrutin (règle R-4.3) est supprimée à l'expiration d'un délai de deux mois courant à compter de son import, dès lors qu'aucun scrutin ne se trouve alors à l'état `brouillon` ou `annoncé` (règle R-3.10) — les deux seuls états dans lesquels un scrutin la figera encore lors de son ouverture. Seule la provenance de l'import (nom du fichier, empreinte, nombre de lignes, opérateur, date) est alors conservée, au journal d'audit ; les données d'identité elles-mêmes ne le sont pas.

**R-13.4** Les sels servant à la dérivation des jetons sont propres à chaque scrutin, de sorte que la plateforme ne permette aucun rapprochement de la participation d'une même personne à deux scrutins distincts. Aucun état de participation inter-scrutins n'est fourni.

**R-13.4 bis** Le nom et la date de naissance constituant des identifiants stables, la garantie énoncée à la règle R-13.4 ne vaut que pour les traitements opérés par la plateforme : un accès direct aux données de deux scrutins concomitants permettrait de rapprocher les participations par leur moyen. Le risque, qui porte sur la seule participation et non sur le contenu des bulletins, est circonscrit par la restriction de l'accès aux données d'identité au seul administrateur de scrutin et par la durée de conservation fixée à la règle R-13.3. Son acceptation relève de la commune.

**R-13.5** Les adresses IP, lorsqu'elles sont enregistrées aux fins de limitation du nombre de requêtes, ne sont pas conservées au-delà de ce qui est nécessaire à cette seule fin.

**R-13.6** Un export réel de la liste électorale constitue une donnée personnelle relative à chaque électeur de la commune. Il n'est jamais placé dans le dépôt de sources, dans la suite de tests ni dans un rapport d'anomalie ; les données d'essai sont synthétiques.

---

## 14. Accessibilité, présentation et langues

**R-14.1** L'interface publique et l'interface d'administration sont conformes au RGAA, s'agissant d'un service public en ligne.

**R-14.2** L'interface est utilisable depuis un téléphone mobile.

**R-14.3** L'interface est disponible en français par défaut et, si la configuration le prévoit, dans d'autres langues. Les textes d'interface sont traduits par catalogue ; l'intitulé, la description et les libellés d'options d'un scrutin sont traduits pour chaque langue activée. Un scrutin ne peut être ouvert tant qu'une traduction fait défaut, et une traduction manquante s'efface au profit de la langue par défaut du scrutin plutôt que du vide. Le français demeure la version faisant foi : en cas de divergence entre une traduction et le texte français, ce dernier prévaut, et les pages emportant des effets de droit — les mentions prévues aux règles R-1.4 et R-13.2 — l'indiquent.

---

## 15. Points restant à arrêter

1. Pour chaque scrutin : ses propositions, dans chacune des langues activées, et ses dates d'ouverture et de clôture.
2. L'identité du référent visé à la règle R-13.2.
3. Pour chaque scrutin : les options de forme retenues pour la voie papier au titre de la règle R-8.2.
4. L'acceptation par la commune du risque résiduel exposé à la règle R-13.4 bis.
5. **Le point de savoir si toutes les inscriptions sont soumises à examen, ou seulement celles que la règle R-5.4 y renvoie.** Compte tenu de la règle R-5.12, une correspondance exacte établit moins qu'il n'y paraît ; l'examen systématique constitue la position la plus solide et, à l'échelle d'une petite commune, une position abordable.
6. **Le point de savoir si les inscriptions s'ouvrent avant le vote.** En l'état, la copie figée est constituée à l'ouverture du scrutin, de sorte que inscription, examen et vote débutent au même instant, et qu'un électeur s'inscrivant peu avant la clôture peut se trouver hors d'état de voter à temps. Une période d'inscription distincte, la copie étant figée à son commencement, y remédierait.
