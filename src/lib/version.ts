import { version,releaseChannel } from '../../package.json';

/** The packager verifies this version against the native executable and locks. */
export const appVersion = version;
export const developmentBuild=releaseChannel==='development';
