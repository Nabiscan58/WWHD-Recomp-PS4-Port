# wwhd-ps4 — The Wind Waker HD (Wii U) sur PS4 (GoldHEN)

Portage PS4 de [Wind Waker HD Recomp](https://github.com/ZeldaWWHDRecomp/ZeldaWWHDRecomp) (la recompilation statique
du jeu Wii U : code PowerPC traduit en C, GX2 réimplémenté sur Vulkan), sur le modèle des portages PS4 de
[SMW](https://github.com/iHaiDeeZ/SMW) et [SSBU](https://github.com/iHaiDeeZ/SSBU) : pas d'émulateur, le code du jeu
est compilé pour le processeur Jaguar de la PS4 et dessiné avec le pilote Vulkan RADV de Mesa porté sur le GPU de la
PS4.

**Aucun jeu, aucun code du jeu, aucune clé ici.** Le paquet se fabrique sur ton PC à partir de ta propre copie.

> **État (0.1.12) : le jeu démarre et se joue sur une PS4 Slim (GoldHEN), mais lentement : 14 à 16 images/s en jeu.**
> Le goulot est le processeur Jaguar (préparation des commandes graphiques sur un seul cœur), pas le GPU. Tout ce qui
> a été trouvé, mesuré et essayé, et les pistes pour aller plus loin : [`docs/ETAT.md`](docs/ETAT.md). Les
> contributions sont bienvenues.

**English:** a PS4 (GoldHEN) port of Wind Waker HD Recomp. A Windows tool (the Maker) builds a `.pkg` from your own
copy of the game. It boots and plays on a PS4 Slim at 14-16 fps in game; the bottleneck is the Jaguar CPU (one core
preparing ~3,500 draws a frame), not the GPU. See [`docs/STATUS.md`](docs/STATUS.md) for the findings and where help
is needed.

## Pour jouer : WWHD-PS4 Maker (Windows)

Le zip `WWHD-PS4-Maker-<version>.zip` contient un programme Windows qui fait tout (voir `maker/LISEZ-MOI.txt`) :

1. **Outils** — au premier lancement il télécharge (SHA-256 vérifiés, dans `tools\`) LLVM 21.1.8, la toolchain
   OpenOrbis v0.5.2 et le SDK PS4 de SMW (RADV + libc++ 21) ; et si aucun .NET n'est installé, le runtime .NET 8
   portable de Microsoft pour PkgTool, dès cette étape. Téléchargements repris après une coupure (Range), avec
   attente du retour de la connexion (45 min).
2. **Fichiers du jeu** — extraits de ton image `.wud`/`.wux` (avec ses clés) ou archive Cemu `.wua` par l'extracteur
   du projet d'origine (`wwhd-extract`), ou ton dossier extrait tel quel. Version 0 USA ou Europe, vérifiée par
   SHA-256 (le code de setup d'origine).
3. **Traduction** — `tools/recomp/recomp.py` du projet d'origine : PowerPC → C.
4. **Compilation PS4** — clang 21 `--target=x86_64-pc-freebsd12-elf -march=btver2`, mêmes options que le runtime ;
   édition de liens avec le runtime PS4 précompilé (`sdk/`) et RADV, puis `create-fself` → `eboot.bin`.
5. **Paquet** — `param.sfo`, icônes (art original), modules système, et par défaut les fichiers du jeu dans
   `/app0/game` ; projet GP4 écrit par le Maker, `PkgTool pkg_build` → `WWHD-PS4-<version>.pkg`.
6. **FTP (option)** — le `.pkg` dans `/data/pkg` (serveur FTP de GoldHEN), et en mode « fichiers par FTP » le jeu dans
   `/data/WWHD/game`.

Ligne de commande équivalente : `tools\python\python.exe maker\wwhd_ps4_maker.py --game <image|archive|dossier>
[--disc-key F] [--common-key F] --out <dossier> [--data in-pkg|ftp] [--ftp IP:2121]`.

## Comment le portage fonctionne

| | PC (projet d'origine) | PS4 (ce dépôt) |
|---|---|---|
| Code du jeu | PowerPC → C, clang | idem, clang 21 pour Jaguar (`-march=btver2`, sans contraction FMA) |
| Mémoire invitée | fenêtre de 4 Gio à `0x2000_0000_0000` | fenêtre de 4 Gio à `0x30_0000_0000` (sous la zone `0x40_0000_0000` que RADV réserve pour le GPU), **réservée** ; des blocs de 64 Kio de mémoire directe sont mappés au premier accès (gestionnaire SIGSEGV, `port/ps4_memory.cpp`, d'après SMW) ; pré-mappage avant les lectures noyau (`read()` dans la mémoire invitée) et avant la protection en écriture (suivi des textures) |
| Piles des threads invités | 64 Mio | 64 Mio d'espace d'adresses, mappés à l'usage (même mécanisme), 1 Mio pré-mappé |
| Fenêtre, manettes, son | SDL3 | SDL 3.4.18 avec **pilotes PS4 écrits pour ce projet** (`patches/sdl3-3.4.18-ps4.patch`) : vidéo « ps4 » (1920×1080, Vulkan via `VK_EXT_headless_surface`), manettes ScePad (DualShock 4 annoncée comme telle, gyro, accéléromètre, pavé tactile, vibration, barre lumineuse, jusqu'à 4 joueurs), son sceAudioOut (48 kHz, flottant stéréo) |
| Vulkan | chargeur système | RADV (Mesa, winsys GNM de Crema) lié statiquement + WSI VideoOut (`port/ps4_vk_wsi.cpp`, de SSBU/SMW ; ici avec un format sRGB pour l'image finale) |
| Tas, threads, plantages | système | runtime PS4 de SMW (`port/`) : dlmalloc, crt1 avec table de remplacement de malloc, pthread sur les 6 cœurs, journal de démarrage et de plantage |
| Données | dossier du jeu | `/data/WWHD` (sauvegardes, réglages, caches, journaux, `env.txt`) ; jeu dans `/app0/game` ou `/data/WWHD/game` |

Changements dans le projet d'origine (`patches/wwhd-ps4.patch`, sur le commit de `patches/BASE.txt`) : base de la
fenêtre invitée, réservation paresseuse, taille de page 16 Kio, pré-mappage du suivi d'écriture, piles paresseuses,
démarrage PS4 (`wwhd_ps4_startup`), rapport de plantage enchaîné à celui du port, adresses de plantage en adresses ELF,
branche CMake `PS4`.

Contrôles : Croix/Rond/Carré/Triangle = A/B/X/Y (réglable dans les Réglages du jeu), clic du pavé tactile = « − »,
**L3 + R3 = Home** (ouvre les Réglages du portage : la PS4 ne donne pas le bouton PS aux applications).

### Optimisation à l'édition des liens (0.1.11)

Le C++ du runtime (hors `port/`, hors code du jeu, hors bibliothèques) est compilé en bitcode ThinLTO (option
`PS4_LTO` du CMakeLists patché). `scripts/make-sdk.py` en fait un seul objet natif, `sdk/obj/runtime-lto.o`, avec
`ld.lld -r --lto-O3` : l'optimisation entre fichiers (inlining entre `gx2/` et `gfx/vulkan/`, où le thread de rendu
passe son temps) est faite une fois au build du SDK, et l'édition des liens du Maker reste aussi rapide qu'avant.
Vérifié : tous les appels à malloc/free/calloc, pthread_create, clock_gettime et mmap du runtime passent toujours par
les `--wrap` de `port/ps4_runtime.cpp`.

## Pour les mainteneurs : construire le SDK et le Maker (Linux ou WSL)

```
scripts/build-sdk.sh ~/wwhd-ps4-build        # toolchains, SDL3/glslang/LZ4 pour PS4, runtime + eboot de test, sdk/
maker/build-bundle.sh ~/wwhd-ps4-build       # le zip du Maker Windows (apt install mono-mcs mono-devel zip)
```

`toolchain/ps4.cmake` est une toolchain CMake autonome (LLVM 21 + OpenOrbis + sysroot libc++ 21 de SMW), utilisable
depuis Linux ou Windows. Note : `--sysroot` et non `-isysroot` (sinon clang lit les en-têtes `/usr/include` de la
machine), et `-z nodynamic-undefined-weak` (sinon `create-fself` refuse les fonctions d'initialisation `thread_local`).

## Diagnostic sur la console

- `/data/WWHD/boot-trace.log` : étapes du démarrage (modules, mémoire, swapchain, premiers flips).
- `/data/WWHD/gpu/radv-ps4.log` (+ `gpu-hang.txt`, `gpu-fault.txt`) : le winsys RADV ; les chemins `/data/Crema/`
  de `libamd_common.a` sont remplacés par `/data/WWHD//` (`scripts/patch-radv-paths.py`).
- `/data/WWHD/crash.log` : registres, adresses de code sur la pile (adresses ELF : `llvm-symbolizer --obj=wwhd.elf
  0x...`, `wwhd.elf` est dans le dossier de sortie du Maker), état de tous les threads.
- `/data/WWHD/captures/wwhd.log` et `captures/crash-*.log` : le journal du jeu et son rapport de plantage (registres
  invités, chaîne d'appels du jeu).
- `env.txt` accepte tous les réglages `WWHD_*` du projet d'origine.

## Contribuer

Le plus utile maintenant : les performances (voir [`docs/ETAT.md`](docs/ETAT.md), « Pistes pour la suite »). Pour un
retour de console, joindre `boot-trace.log`, `captures/wwhd.log` (avec `WWHD_PROFILE=1`), une photo de l'overlay
(L3+R3) et, pour `samples.log` ou `hang.log`, le `wwhd-symbols.txt` du même build.

## Licences et crédits

Le Maker contient aussi PkgTool reconstruit depuis LibOrbisPkg (maxton, LGPL-3.0), avec une seule modification (la place des empreintes PlayGo, comme BOTW et SMW) : `scripts/build-pkgtool.sh`.

Le code de ce dépôt est sous licence MIT (voir `LICENSE`) ; les modifications du projet d'origine
(`patches/wwhd-ps4.patch`) restent sous MPL-2.0 comme lui ; les nouveaux fichiers de SDL sont sous licence zlib. Merci à ZeldaWWHDRecomp (la recompilation et le runtime),
iHaiDeeZ / ShiroKlein et BelmanteGu (SMW, SSBU : runtime PS4, WSI, SDK), Crema / DolphinPS4 (RADV sur GNM),
OpenOrbis, LLVM, SDL, glslang, LZ4, zstd, Cemu. Projet de fans sans lien avec Nintendo ni Sony.
