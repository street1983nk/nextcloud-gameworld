// All areas of the de dictionary; mergeAreas throws on a duplicate key.
import { mergeAreas } from '../merge.js'
import admin from './admin.js'
import core from './core.js'
import kids from './kids.js'
import parent from './parent.js'
import world from './world.js'

export default mergeAreas({ core, parent, admin, kids, world })
