var original_papers;

function update_papers(data) {
    var template = $("#paper-template").html();
    var html = Mustache.render(template, data);
    $("#papers_score").html(html);
}
$.get('/wayr/current_votes', function(data) {
    original_papers = data;
    update_papers(data);
});

$("body").on('click', '#vote', function(e) {
    var res = [];
    var button = $(this);
    $(this).prop("disabled",true);
    $('.paper-option:checked').each(function() {res.push(this.id)});
    $.ajax({
        type: "POST",
        url: '/wayr/vote',
        data: JSON.stringify({'ids': res}),
        contentType: "application/json"
    })
    .done(function(data) {
        $('.message').html(data.message);
    })
    .always(function() {
        $(button).prop("disabled",false);
    });
});

$('#searchInput').on('input', function(e) {
  if (e.which == 13 || $(this).val().length < 2) {
    return false;    //<---- Add this line
  }
  $.get('/wayr/autocomplete?q=' + $(this).val()).done(function(data) {
    if (data.data !== undefined && data.data.length > 0) {
        update_papers(data);
    }
  })
});


var sticky_top = $('#vote').offset().top;

$(window).scroll(function (event) {
    var y = $(this).scrollTop();
    if (y + 10 >= sticky_top) {
      $('#vote').addClass('sticky');
      $('#main_section').css('margin-top', `${15 + $('#vote').outerHeight()}px`)
    }
    else {
        $('#main_section').css('margin-top', '15px')
        $('#vote').removeClass('sticky');
    }
});
