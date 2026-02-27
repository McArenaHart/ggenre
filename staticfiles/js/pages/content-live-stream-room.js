(function () {
  "use strict";

  window.addEventListener("load", function () {
    const body = document.body;
    const roomID = body.getAttribute("data-room-name") || "";
    const role = body.getAttribute("data-role") || "Audience";

    if (!roomID || typeof ZegoUIKitPrebuilt === "undefined") {
      return;
    }

    const userID = Math.floor(Math.random() * 10000) + "";
    const userName = "User" + userID;

    // NOTE: kept for compatibility with current flow.
    const appID = 236901691;
    const serverSecret = "3b7ec14419a63833662937d91c0d3a0a";

    const kitToken = ZegoUIKitPrebuilt.generateKitTokenForTest(
      appID,
      serverSecret,
      roomID,
      userID,
      userName
    );

    const zegoRole = role === "Host" ? ZegoUIKitPrebuilt.Host : ZegoUIKitPrebuilt.Audience;

    const zp = ZegoUIKitPrebuilt.create(kitToken);
    zp.joinRoom({
      container: document.querySelector("#root"),
      scenario: {
        mode: ZegoUIKitPrebuilt.LiveStreaming,
        config: { role: zegoRole },
      },
      sharedLinks: [
        {
          name: "Join as an audience",
          url:
            window.location.protocol +
            "//" +
            window.location.host +
            window.location.pathname +
            "?roomID=" +
            roomID +
            "&role=Audience",
        },
      ],
      turnOnCameraWhenJoining: zegoRole === ZegoUIKitPrebuilt.Host,
      showMyCameraToggleButton: zegoRole === ZegoUIKitPrebuilt.Host,
      showScreenSharingButton: zegoRole === ZegoUIKitPrebuilt.Host,
      showTextChat: true,
      showUserList: true,
    });
  });
})();
