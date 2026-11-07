# État du portage et journal de bord

*[English version](STATUS.md)*

Ce document résume où en est le portage, ce qui a été trouvé et corrigé pendant les essais sur console, et ce qu'il
reste à faire. Il est fait pour que d'autres puissent reprendre le travail sans refaire le chemin.

Console de test : PS4 Slim CUH-2016A, firmware 10.01, GoldHEN 2.4b18.10. Jeu : The Wind Waker HD, version EU
(titre 0005000010143600).

## En bref

- **Le jeu démarre et se joue** (depuis la 0.1.5) : son correct, manette DualShock 4, sauvegardes dans
  `/data/WWHD/save`.
- **Il est lent** : 25 à 30 images/s sur l'écran titre, **14 à 16 images/s en jeu** (île de l'Aurore, face au
  village). Le goulot est le **processeur**, pas le GPU (voir « Performances »).

## Ce qui a été trouvé sur console (dans l'ordre)

| Version | Problème | Cause | Correction |
| --- | --- | --- | --- |
| 0.1.0 | Gel au lancement, touche PS sans effet | Supposée : la mémoire invitée occupait la zone d'adresses GPU que RADV réserve (`0x40_0000_0000`) | Mémoire invitée à `0x30_0000_0000`, piles à `0x34–0x3C` (gardé, mais ce n'était pas la cause) |
| 0.1.2–0.1.4 | Toujours le gel | Diagnostic : le thread principal reste bloqué dans `sceKernelMapDirectMemory` avec accès GPU (`prot 0x33`), au tout premier bloc mémoire du pilote | Voir 0.1.5 |
| 0.1.5 | **Le jeu démarre** | Le paquet utilisait l'identité de RetroArch (`CATEGORY gde`, application), prévue pour OpenGL/Piglet. Vulkan sur GNM demande l'identité homebrew « plain » (`APP_TYPE 1`, `CATEGORY gd`, `ATTRIBUTE 2`, sans `right.sprx`), comme SMW, SSBU, BOTW, TOTK | `param.sfo` « plain ». Bonus : la PS4 donne le 7e cœur et 332 Mo de mémoire flexible au lieu de 255 |
| 0.1.3 | Gel immédiat, aucun journal | Les enveloppes `--wrap` des appels noyau appelaient `getenv` pendant le démarrage de la libc (le tas s'initialise depuis la libc) | 0.1.4 : rien d'autre qu'un passage direct tant que le traçage n'est pas activé |
| 0.1.5 | 1 image/s | Les outils de diagnostic (enregistreur de vol RADV, `fsync` toutes les secondes) | Coupés par défaut (0.1.6) |
| 0.1.5 | `env.txt` ignoré, pas de `wwhd.log` | Pas de dossier courant sur PS4 (`getcwd` échoue) : les chemins relatifs ne mènent nulle part. Les sauvegardes auraient échoué aussi | Chemins absolus partout (0.1.6) |
| 0.1.6 | Paquet de 100 Mo sans le jeu | PkgTool (OpenOrbis) plante sur certaines tailles de paquet : « Playgo Chunk hash file was not allocated enough space » (reproduit à 2,2 Go) | PkgTool reconstruit avec de la marge, comme BOTW/SMW : `scripts/build-pkgtool.sh` (0.1.7) |
| — | `/data/WWHD` absent après un arrêt forcé | L'entrée du dossier n'était pas écrite sur le disque ; sur certaines consoles l'application ne peut pas créer de dossier dans `/data` | `fsync` du dossier (0.1.5) ; sinon le créer par FTP |
| 0.1.8 | Thread principal SDL à ~45 % d'un cœur | Manette lue ~1000 fois/s, horloge SDL (`CLOCK_MONOTONIC_PRECISE`) par appel système | Lecture de la manette toutes les 4 ms, horloge sur le TSC (0.1.9) |

## Performances

Mesures en jeu, île de l'Aurore face au village, 1x (1280×720), mode 30 i/s, enregistrement Vulkan sur un second
thread, écran de la mablette en « picture-in-picture automatique », améliorations graphiques coupées :

| | ms par image |
| --- | --- |
| Thread de rendu (préparation des commandes) | 61–66 |
| Jeu (code traduit) | ~34 |
| GPU | ~5,5 |

Rapport du profileur intégré du moteur (`WWHD_PROFILE=1`, 0.1.11) :

- **~3 560 dessins par image**, 17,5 µs chacun ; ~42 000 écritures de registres GX2 (10 ms).
- Par étape de dessin (ms/image) : constantes des shaders 15,4 · copie des sommets 9,1 · recherche du shader 7,8 ·
  textures 6,2 · enregistrement 4,5 · soumission 4,7 · index 4,4 · descripteurs 3,8 · cibles 3,4 · pipeline 1,7.
- Envois au GPU : ~11 Mio/image, dont 8,8 Mio de sommets (2,1 Mio uniques : le jeu réécrit ces zones à chaque image).
- Le jeu attend le rendu ~33 ms par image (`DrawDone`).

Pour comparer : la documentation du moteur (`docs/vulkan.md` du projet d'origine) mesure **~5 ms** pour le thread de
rendu sur cette même scène avec un Apple M3 Max. Un cœur Jaguar est environ 13 fois plus lent. Le moteur est déjà très
optimisé (15 chemins rapides actifs par défaut) : le problème est la quantité de travail sur un seul cœur lent.

Ce qui a été essayé :

| Essai | Effet |
| --- | --- |
| Enregistrement Vulkan sur un second thread + mablette en PiP automatique | Render CPU 74 → 61,5 ms, 13 → 16 i/s |
| Améliorations graphiques coupées (AO, profondeur pleine taille, torches, nuages) | Peu d'effet côté processeur |
| ThinLTO du runtime (0.1.11) | Non mesurable : le profileur actif ce jour-là coûtait lui-même quelques ms |
| Zone d'envoi en mémoire « onion » mise en cache (0.1.12, `WWHD_VK_UPLOAD_CACHED`) | À mesurer |

## Pistes pour la suite

1. **Répartir la préparation des dessins sur plusieurs cœurs.** C'est le seul levier capable d'un vrai bond : le
   Jaguar a 6 à 7 cœurs, le rendu n'en utilise vraiment qu'un. Refonte importante du moteur (`gx2/`, `gfx/vulkan/`).
2. **Le code du jeu** (~34 ms) plafonne à ~28 i/s même avec un rendu instantané : options de compilation du code
   traduit, PGO, fonctions chaudes du jeu (profileur `WWHD_PS4_PROFILE=1`).
3. **Gains ciblés dans le moteur**, mesurés avec `WWHD_PROFILE=1` : constantes des shaders (15 ms), recherche du
   shader (8 ms), registres (10 ms).

Un utilisateur de Reddit (Orpheuseyes) a dit avoir fait tourner WWHD de manière fluide sur PS4 avec le même
recompilateur, en se promenant à Mercantile, avant d'effacer ses vidéos sans partager le projet : il y a sans doute
plus à gagner que ce que les chiffres ci-dessus laissent penser.

## Collecter des mesures

Sur la console, dans `/data/WWHD/env.txt` (une ligne `NOM=valeur` par réglage) :

- `WWHD_PROFILE=1` : rapport détaillé du moteur toutes les 120 images dans `captures/wwhd.log` ;
- `WWHD_PS4_PROFILE=1` : échantillonneur, une minute à partir de 45 s, dans `samples.log` ; les adresses se lisent
  avec `wwhd-symbols.txt` (dossier de sortie du Maker) ;
- `WWHD_GPU_TRACE=1` : enregistreur de vol RADV (`gpu/flight`), très coûteux ;
- `WWHD_KTRACE=1` : trace des appels noyau du pilote au démarrage.

L'overlay de performance du jeu (menu L3+R3) affiche Game CPU, Render CPU et GPU.
