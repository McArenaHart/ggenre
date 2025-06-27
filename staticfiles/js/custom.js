(function($) {
  "use strict"; // Start of use strict
  // Prevent the content wrapper from scrolling when the fixed side navigation hovered over
  $('body.fixed-nav .sidebar').on('mousewheel DOMMouseScroll wheel', function(e) {
    if ($window.width() > 768) {
      var e0 = e.originalEvent,
        delta = e0.wheelDelta || -e0.detail;
      this.scrollTop += (delta < 0 ? 1 : -1) * 30;
      e.preventDefault();
    }
  });
  
  // Category Owl Carousel
  var objowlcarousel = $(".owl-carousel-category");
  if (objowlcarousel.length > 0) {
	 objowlcarousel.owlCarousel({
		items: 8,
		lazyLoad: true,
		pagination: false,
		loop: true,
		autoPlay: 2000,
		navigation: true,
		stopOnHover: true,
		navigationText: ["<i class='fa fa-chevron-left'></i>", "<i class='fa fa-chevron-right'></i>"]
	});
  }

  // Login Owl Carousel
  var mainslider = $(".owl-carousel-login");
  if (mainslider.length > 0) {
      mainslider.owlCarousel({
          items: 1,
          lazyLoad: true,
          pagination: true,
          autoPlay: 4000,
		 loop: true,
		singleItem: true,
          navigation: false,
          stopOnHover: true,
		navigationText: ["<i class='mdi mdi-chevron-left'></i>", "<i class='mdi mdi-chevron-right'></i>"]
      });
  }
	
  // Tooltip
  $('[data-toggle="tooltip"]').tooltip()

  // Scroll to top button appear
  $(document).on('scroll', function() {
    var scrollDistance = $(this).scrollTop();
    if (scrollDistance > 100) {
      $('.scroll-to-top').fadeIn();
    } else {
      $('.scroll-to-top').fadeOut();
    }
  });

  // Smooth scrolling using jQuery easing
  $(document).on('click', 'a.scroll-to-top', function(event) {
    var $anchor = $(this);
    $('html, body').stop().animate({
      scrollTop: ($($anchor.attr('href')).offset().top)
    }, 1000, 'easeInOutExpo');
    event.preventDefault();
  });

})(jQuery); // End of use strict



  
  document.addEventListener('DOMContentLoaded', () => {
      document.querySelectorAll('.add-comment-form').forEach((form) => {
          form.addEventListener('submit', async (event) => {
              event.preventDefault(); // Prevent page reload
  
              const formData = new FormData(form);
              const url = form.action;
              const commentSection = form.closest('.card-footer');
              const commentCountElement = commentSection.querySelector(".comment-count");
  
              try {
                  const response = await fetch(url, {
                      method: 'POST',
                      body: formData,
                      headers: {
                          'X-CSRFToken': formData.get('csrfmiddlewaretoken'),
                          'X-Requested-With': 'XMLHttpRequest',
                      },
                  });
  
                  const data = await response.json();
  
                  if (data.status === 'success') {
                      // Create new comment HTML
                      const newComment = document.createElement('div');
                      newComment.classList.add('border', 'rounded', 'p-2', 'mb-2', 'bg-white', 'd-flex', 'align-items-center');
                      newComment.innerHTML = `
                          <img src="${data.comment.user_profile}" alt="${data.comment.user}" class="rounded-circle me-2" width="30" height="30">
                          <div>
                              <p class="mb-0"><a href="/user/${data.comment.user_id}/"><strong>${data.comment.user}</strong></a> - ${data.comment.timestamp}</p>
                              <p>${data.comment.text}</p>
                          </div>
                      `;
  
                      // Insert comment before the form
                      commentSection.insertBefore(newComment, form);
  
                      // Update comment count
                      if (commentCountElement) {
                          commentCountElement.textContent = data.comment_count;
                      }
  
                      // Clear the input field
                      form.querySelector('textarea[name="text"]').value = '';
                  } else {
                      alert(data.message || 'An error occurred while adding the comment.');
                  }
              } catch (error) {
                  console.error('Error:', error);
                  alert('Failed to add the comment. Please try again.');
              }
          });
      });
  });
  
  function incrementViews(contentId) {
      const csrfTokenElement = document.querySelector('[name=csrfmiddlewaretoken]');
      const csrfToken = csrfTokenElement ? csrfTokenElement.value : null;
  
      if (!csrfToken) {
          console.error("CSRF token not found!");
          return;
      }
  
      const url = new URL(`/content/increment-views/${contentId}/`, window.location.origin);
      console.log("Fetching URL:", url.href); // Debugging
  
      fetch(url.href, {
          method: "POST",
          headers: {
              "X-CSRFToken": csrfToken,
              "X-Requested-With": "XMLHttpRequest"
          },
          credentials: "same-origin"
      })
      .then(response => {
          if (!response.ok) {
              throw new Error(`HTTP error! Status: ${response.status}`);
          }
          return response.json();
      })
      .then(data => {
          console.log("Success:", data);
          
          // Find and update the corresponding view count on the page
          const viewCountElement = document.querySelector(`.view-count[data-content-id="${contentId}"]`);
          if (viewCountElement && data.new_views) {
              viewCountElement.textContent = data.new_views;  // Update the UI with new view count
          }
      })
      .catch(error => console.error("Error updating views:", error));
  }
  
  document.addEventListener('DOMContentLoaded', function() {
      const mediaElements = document.querySelectorAll('video, audio');
  
      mediaElements.forEach(media => {
          let hasIncremented = false;
  
          media.addEventListener('timeupdate', function() {
              if (!hasIncremented && media.currentTime >= 5) {
                  const card = media.closest('.card');
                  const viewCountElement = card ? card.querySelector('.view-count') : null;
                  const contentId = viewCountElement ? viewCountElement.getAttribute('data-content-id') : null;
  
                  if (contentId) {
                      incrementViews(contentId);
                      hasIncremented = true; // Ensure the view is only incremented once
                  } else {
                      console.error("Content ID not found!");
                  }
              }
          });
  
          // Reset the flag if the user seeks back before 5 seconds
          media.addEventListener('seeked', function() {
              if (media.currentTime < 5) {
                  hasIncremented = false;
              }
          });
      });
  });
  
  

  $(document).ready(function(){
    $(".owl-carousel-login").owlCarousel({
      items: 1,
      loop: true,
      autoplay: true,
      autoplayTimeout: 5000,
      nav: false,
      dots: true
    });
  });



  function filterContent() {
    const searchQuery = document.getElementById('searchInput').value.toLowerCase().trim();
    const selectedCategory = document.getElementById('categoryFilter').value.toLowerCase().trim();
    const items = document.querySelectorAll('.content-item');
    
    items.forEach(item => {
        const title = item.getAttribute('data-title') || "";
        const artist = item.getAttribute('data-artist') || "";
        const category = item.getAttribute('data-category') || "";
        const votes = parseInt(item.getAttribute('data-votes')) || 0;
        
        const matchesSearch = title.includes(searchQuery) || artist.includes(searchQuery);
        const matchesCategory = selectedCategory === "" || category === selectedCategory;
        const matchesVotes = votes >= 5;  // Show only content with 5+ votes

        item.style.display = matchesSearch && matchesCategory && matchesVotes ? "" : "none";
    });
}



function fetchAnnouncements() {
    fetch('/api/announcements/')
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }
        return response.json(); // Parse JSON
    })
    .then(data => {
        if (data.announcements && data.announcements.length > 0) {
            showPopup(data.announcements);
        }
    })
    .catch(error => {
        console.error("Error fetching announcements:", error);
    });
}
