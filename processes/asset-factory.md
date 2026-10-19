# Asset factory loop

A pack can be made with no game project. Read the brief and decide the pack:
shaders, UI sounds or meshes, and what the buyer should be able to do with it.

Draft the source with the `asset-factory` skill: a spec in `factory/spec/packs/`
plus the shader or generator. Run `init`, then `build`. Read each gate failure,
fix the source and rebuild. Do not edit `factory/build/` or `factory/dist/`.

Hand the build to the user. Approval means the user listened to the sounds or
looked at the previews in all renderers. The agent never approves for them.
Then the user approves, and `package` writes `factory/dist/<pack>/` with
VERIFY.md, manifest.json and the zip.

Prepare the listing from the packaged files. The disclosure text must say
plainly where AI assisted. Check each license with the user before marking it
commercial. The user publishes; the agent does not.

Game projects may consume packs from `factory/dist/<pack>/addons/`. Keep that
copy one-way: improve the pack in `factory/`, repackage, then update the game.
