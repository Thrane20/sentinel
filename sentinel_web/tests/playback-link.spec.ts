import {expect,test} from "@playwright/test";
import {parsePlaybackLink} from "../lib/playback-link";

test("playback URL parsing validates camera and original timestamp",()=>{
  const now=1792284000;
  const valid=parsePlaybackLink("?playback=1&camera=05&at=1788764730&event=old",now);
  expect(valid.kind).toBe("playback");
  if(valid.kind==="playback") {expect(valid.camera.id).toBe("05");expect(valid.at).toBe(1788764730);}
  expect(parsePlaybackLink("?tab=animals&event=old",now).kind).toBe("none");
  for(const search of ["?playback=1&camera=99&at=1","?playback=1&camera=05","?playback=1&camera=05&at=NaN","?playback=1&camera=05&at=0","?playback=1&camera=05&at=1.5","?playback=1&camera=05&at=999999999999999999","?playback=1&camera=05&at=1792284061","?playback=oops&camera=05&at=1"])
    expect(parsePlaybackLink(search,now).kind).toBe("invalid");
});
